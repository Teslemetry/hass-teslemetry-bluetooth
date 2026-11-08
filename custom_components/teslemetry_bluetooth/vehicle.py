"""Bluetooth-only command access to a Teslemetry vehicle."""

from collections.abc import Callable
from typing import Any

from bleak.exc import BleakError
from tesla_fleet_api import firmware_at_least
from tesla_fleet_api.exceptions import TeslaFleetError
from tesla_fleet_api.router import VehicleRouter
from tesla_protocol.command.vcsec_pb2 import VehicleSleepStatus_E

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntry

from .const import ACCEPTED_REASONS, CLIMATE_STREAMING_FIRMWARE, DOMAIN, LOGGER

# Failures a Bluetooth command can raise. TeslaFleetError is a BaseException,
# and the library raises ValueError when the session key is missing.
BLUETOOTH_ERRORS = (TeslaFleetError, BleakError, OSError, ValueError)


class TeslemetryBluetoothVehicle:
    """A Teslemetry vehicle reached only through its Bluetooth backend.

    Teslemetry's VehicleRouter sends each command to its Bluetooth primary and
    falls back to the cloud. This class uses the router only for Teslemetry's
    in-range check and calls the Bluetooth primary directly, so a command
    never reaches the cloud backend.
    """

    def __init__(
        self,
        router: VehicleRouter[Any, Any],
        vin: str,
        device: DeviceEntry,
        data: Any,
        config: dict[str, Any],
    ) -> None:
        """Initialize the vehicle."""
        self.router = router
        self.vin = vin
        # Teslemetry's TeslemetryVehicleData, read only for the car's own limits
        # and whether Teslemetry streams the car.
        self.data = data
        # The vehicle config from Teslemetry's metadata, read for the car's options.
        self.config = config
        # Teslemetry's own device for the vehicle; entities attach to it.
        self.device = device
        self.name = device.name_by_user or device.name or vin
        self.in_range = False
        self._listeners: list[Callable[[], None]] = []

    @property
    def streaming(self) -> bool:
        """Return if Teslemetry reads this vehicle from its stream."""
        # Teslemetry polls a vehicle set to poll, or with older firmware.
        return not self.data.poll and firmware_at_least(self.data.firmware, "2024.26")

    @property
    def climate_polled(self) -> bool:
        """Return if Teslemetry reads the car's climate from its vehicle coordinator."""
        return bool(self.data.poll) or not firmware_at_least(
            self.data.firmware, CLIMATE_STREAMING_FIRMWARE
        )

    @property
    def cop_temperature_supported(self) -> bool:
        """Return if the car can set its cabin overheat protection temperature."""
        # The same sources Teslemetry's cabin overheat protection entity reads.
        if self.climate_polled:
            return bool(
                self.data.coordinator.data.get(
                    "vehicle_config_cop_user_set_temp_supported"
                )
            )
        return bool(self.config.get("cop_user_set_temp_supported"))

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call listener when the in-range state changes."""
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    async def async_update_range(self) -> bool:
        """Run Teslemetry's in-range check and notify listeners of a change."""
        # The check also hands the fresh BLE device to the Bluetooth backend.
        in_range = await self.router.is_healthy()
        if in_range != self.in_range:
            self.in_range = in_range
            for listener in list(self._listeners):
                listener()
        return in_range

    async def async_read_charge_on_solar(self) -> bool | None:
        """Read if charge on solar is on, or return None if the car was not read."""
        if not self.in_range:
            return None
        primary = self.router.primary
        try:
            # The read is an infotainment request, which the Bluetooth backend
            # wakes a sleeping car to answer, so read only an awake car.
            status = await primary.vehicle_state()
            if (
                status.vehicleSleepStatus
                != VehicleSleepStatus_E.VEHICLE_SLEEP_STATUS_AWAKE
            ):
                LOGGER.debug(
                    "Vehicle %s is not awake; charge on solar not read", self.vin
                )
                return None
            result = await primary.get_charge_on_solar()
        except BLUETOOTH_ERRORS as err:
            LOGGER.debug(
                "Bluetooth read of charge on solar for %s failed: %s", self.vin, err
            )
            return None
        LOGGER.debug("Bluetooth charge on solar result: %s", result)
        response = result.get("response") if isinstance(result, dict) else None
        if (
            not isinstance(response, dict)
            or response.get("result") is not True
            or (feature := response.get("getChargeOnSolarFeatureResponse")) is None
        ):
            return None
        return bool(feature.charge_on_solar.enabled)

    async def async_send(self, command: str, /, **kwargs: Any) -> None:
        """Send a command over Bluetooth only, raising if the car is not reached."""
        if not await self.async_update_range():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_in_range",
                translation_placeholders={"vehicle": self.name},
            )
        try:
            result = await getattr(self.router.primary, command)(**kwargs)
        except BLUETOOTH_ERRORS as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bluetooth_failed",
                translation_placeholders={
                    "vehicle": self.name,
                    "error": err.message
                    if isinstance(err, TeslaFleetError)
                    else str(err) or type(err).__name__,
                },
            ) from err
        LOGGER.debug("Bluetooth command %s result: %s", command, result)
        response = result.get("response") if isinstance(result, dict) else None
        if not isinstance(response, dict):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_no_response",
                translation_placeholders={"vehicle": self.name},
            )
        if response.get("result") is True:
            return
        reason = str(response.get("reason") or "")
        if reason in ACCEPTED_REASONS:
            return
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={
                "vehicle": self.name,
                "reason": reason or "unknown",
            },
        )

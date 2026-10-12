"""Bluetooth-only command numbers for Teslemetry vehicles."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api import firmware_at_least

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE, PRECISION_WHOLE, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CHARGE_LIMIT_MAX,
    CHARGE_LIMIT_MIN,
    CHARGING_AMPS_MAX,
    CHARGING_AMPS_MIN,
)
from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TeslemetryBluetoothNumberEntityDescription(NumberEntityDescription):
    """Describes a number that sends one command over Bluetooth."""

    argument: str
    native_max_value: float
    # Teslemetry's vehicle_data key for the car's own maximum.
    max_key: str
    # Teslemetry's stream field for the same maximum, if the stream has one.
    max_field: str | None = None


# The key of each description is also the Bluetooth command it sends.
DESCRIPTIONS: tuple[TeslemetryBluetoothNumberEntityDescription, ...] = (
    TeslemetryBluetoothNumberEntityDescription(
        key="set_charge_limit",
        argument="percent",
        native_min_value=CHARGE_LIMIT_MIN,
        native_max_value=CHARGE_LIMIT_MAX,
        max_key="charge_state_charge_limit_soc_max",
        native_step=PRECISION_WHOLE,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.BATTERY,
        mode=NumberMode.BOX,
    ),
    TeslemetryBluetoothNumberEntityDescription(
        key="set_charging_amps",
        argument="charging_amps",
        native_min_value=CHARGING_AMPS_MIN,
        native_max_value=CHARGING_AMPS_MAX,
        max_key="charge_state_charge_current_request_max",
        max_field="ChargeCurrentRequestMax",
        native_step=PRECISION_WHOLE,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    async_add_entities(
        TeslemetryBluetoothNumberEntity(vehicle, description)
        for vehicle in entry.runtime_data.values()
        for description in DESCRIPTIONS
    )


class TeslemetryBluetoothNumberEntity(TeslemetryBluetoothEntity, RestoreNumber):
    """A number that sends its value over Bluetooth.

    It has no state: the current value stays on Teslemetry's own entity.
    Its maximum follows the car's own, from the same source as Teslemetry's
    number, and falls back to the fixed maximum while that is unknown.
    """

    entity_description: TeslemetryBluetoothNumberEntityDescription
    _attr_native_value = None

    def __init__(
        self,
        vehicle: TeslemetryBluetoothVehicle,
        description: TeslemetryBluetoothNumberEntityDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the car's own maximum."""
        await super().async_added_to_hass()
        data = self.vehicle.data
        # Teslemetry reads polled vehicles and old firmware from its vehicle
        # coordinator, and every other vehicle from its stream.
        if data.poll or not firmware_at_least(data.firmware, "2024.26"):
            self._update_max_from_coordinator()
            self.async_on_remove(
                data.coordinator.async_add_listener(self._handle_coordinator_update)
            )
            return
        if (field := self.entity_description.max_field) is None:
            return
        # The stream does not resend a value, so keep the last one over restarts.
        if (
            last_number_data := await self.async_get_last_number_data()
        ) and last_number_data.native_max_value:
            self._attr_native_max_value = last_number_data.native_max_value
        # Listen on the stream itself: the vehicle's listen_* helpers enable the
        # field in the vehicle's streaming config through the cloud. An internal
        # listener also never opens or holds the stream connection by itself.
        self.async_on_remove(
            data.stream_vehicle.stream.async_add_listener(
                self._handle_stream_update,
                {"vin": self.vehicle.vin, "data": {field: None}},
                internal=True,
            )
        )

    def _update_max_from_coordinator(self) -> None:
        """Read the maximum from Teslemetry's vehicle coordinator data."""
        value = self.vehicle.data.coordinator.data.get(self.entity_description.max_key)
        self._set_max(value if isinstance(value, (int, float)) else None)

    def _set_max(self, value: float | None) -> None:
        """Use the car's maximum, or the fixed one when it is unknown or invalid."""
        description = self.entity_description
        self._attr_native_max_value = (
            value
            if value is not None and value >= (description.native_min_value or 0)
            else description.native_max_value
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the maximum from Teslemetry's vehicle coordinator."""
        self._update_max_from_coordinator()
        self.async_write_ha_state()

    @callback
    def _handle_stream_update(self, event: dict[str, Any]) -> None:
        """Update the maximum from Teslemetry's stream."""
        value = event["data"][self.entity_description.max_field]
        # Some vehicles stream integers as strings.
        try:
            self._set_max(int(value))
        except TypeError, ValueError:
            self._set_max(None)
        self.async_write_ha_state()

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Send the value."""
        await self.vehicle.async_send(
            self.entity_description.key,
            **{self.entity_description.argument: int(value)},
        )

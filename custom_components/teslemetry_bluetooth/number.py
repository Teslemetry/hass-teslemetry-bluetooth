"""Bluetooth-only command numbers for Teslemetry vehicles."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api import firmware_at_least

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    PERCENTAGE,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    UnitOfElectricCurrent,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CHARGE_LIMIT_MAX,
    CHARGE_LIMIT_MIN,
    CHARGING_AMPS_MAX,
    CHARGING_AMPS_MIN,
    CLIMATE_STREAMING_FIRMWARE,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
    VOLUME_MAX,
    VOLUME_STEP,
)
from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TeslemetryBluetoothNumberEntityDescription(NumberEntityDescription):
    """Describes a number that sends one command over Bluetooth."""

    # The command arguments that each receive the value.
    arguments: tuple[str, ...]
    value_fn: Callable[[float], float] = int
    native_max_value: float
    # Teslemetry's vehicle_data keys for the car's own minimum and maximum.
    min_key: str | None = None
    max_key: str
    # Teslemetry's stream field for the same maximum, if the stream has one.
    max_field: str | None = None
    # The oldest firmware that Teslemetry streams this value for.
    streaming_firmware: str = "2024.26"


# The key of each description is also the Bluetooth command it sends.
DESCRIPTIONS: tuple[TeslemetryBluetoothNumberEntityDescription, ...] = (
    TeslemetryBluetoothNumberEntityDescription(
        key="set_charge_limit",
        arguments=("percent",),
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
        arguments=("charging_amps",),
        native_min_value=CHARGING_AMPS_MIN,
        native_max_value=CHARGING_AMPS_MAX,
        max_key="charge_state_charge_current_request_max",
        max_field="ChargeCurrentRequestMax",
        native_step=PRECISION_WHOLE,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        mode=NumberMode.BOX,
    ),
    TeslemetryBluetoothNumberEntityDescription(
        key="set_temps",
        arguments=("driver_temp", "passenger_temp"),
        value_fn=float,
        native_min_value=TEMPERATURE_MIN,
        native_max_value=TEMPERATURE_MAX,
        min_key="climate_state_min_avail_temp",
        max_key="climate_state_max_avail_temp",
        streaming_firmware=CLIMATE_STREAMING_FIRMWARE,
        native_step=PRECISION_HALVES,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
    ),
)

# The key is also the Bluetooth command it sends.
VOLUME_DESCRIPTION = NumberEntityDescription(
    key="adjust_volume",
    native_min_value=0,
    native_max_value=VOLUME_MAX,
    native_step=VOLUME_STEP,
    mode=NumberMode.SLIDER,
    entity_registry_enabled_default=False,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers."""
    entities: list[NumberEntity] = []
    for vehicle in entry.runtime_data.values():
        entities.extend(
            TeslemetryBluetoothNumberEntity(vehicle, description)
            for description in DESCRIPTIONS
        )
        entities.append(TeslemetryBluetoothVolumeEntity(vehicle, VOLUME_DESCRIPTION))
    async_add_entities(entities)


class TeslemetryBluetoothNumberEntity(TeslemetryBluetoothEntity, RestoreNumber):
    """A number that sends its value over Bluetooth.

    It has no state: the current value stays on Teslemetry's own entity.
    Its range follows the car's own, from the same source as Teslemetry's
    entity, and falls back to the fixed range while that is unknown.
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
        """Follow the car's own range."""
        await super().async_added_to_hass()
        data = self.vehicle.data
        # Teslemetry reads polled vehicles and old firmware from its vehicle
        # coordinator, and every other vehicle from its stream.
        if data.poll or not firmware_at_least(
            data.firmware, self.entity_description.streaming_firmware
        ):
            self._update_limits_from_coordinator()
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

    def _update_limits_from_coordinator(self) -> None:
        """Read the range from Teslemetry's vehicle coordinator data."""
        data = self.vehicle.data.coordinator.data
        description = self.entity_description
        self._set_limits(
            _number(data.get(description.min_key)) if description.min_key else None,
            _number(data.get(description.max_key)),
        )

    def _set_limits(self, minimum: float | None, maximum: float | None) -> None:
        """Use the car's range, or the fixed one when it is unknown or invalid."""
        description = self.entity_description
        fixed_minimum = description.native_min_value or 0
        if minimum is None:
            minimum = fixed_minimum
        if maximum is None or maximum < minimum:
            maximum = description.native_max_value
        if maximum < minimum:
            minimum = fixed_minimum
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the range from Teslemetry's vehicle coordinator."""
        self._update_limits_from_coordinator()
        self.async_write_ha_state()

    @callback
    def _handle_stream_update(self, event: dict[str, Any]) -> None:
        """Update the maximum from Teslemetry's stream."""
        value = event["data"][self.entity_description.max_field]
        # Some vehicles stream integers as strings.
        try:
            self._set_limits(None, int(value))
        except TypeError, ValueError:
            self._set_limits(None, None)
        self.async_write_ha_state()

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Send the value."""
        description = self.entity_description
        await self.vehicle.async_send(
            description.key,
            **dict.fromkeys(description.arguments, description.value_fn(value)),
        )


class TeslemetryBluetoothVolumeEntity(TeslemetryBluetoothEntity, NumberEntity):
    """A number that sets the media volume over Bluetooth.

    It has no state: the current volume stays on Teslemetry's media player.
    """

    _attr_native_value = None

    def __init__(
        self,
        vehicle: TeslemetryBluetoothVehicle,
        description: NumberEntityDescription,
    ) -> None:
        """Initialize the number."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Send the volume, keeping its fraction of a step."""
        await self.vehicle.async_send(self.entity_description.key, volume=value)


def _number(value: Any) -> float | None:
    """Return a number from Teslemetry's data, or None if it is not one."""
    # bool is an int, but never a range limit.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value

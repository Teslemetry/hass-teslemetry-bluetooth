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
    # Teslemetry's stream listener for the same maximum, if the stream has one.
    max_listener: (
        Callable[[Any, Callable[[int | None], None]], Callable[[], None]] | None
    ) = None


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
        max_listener=lambda x, y: x.listen_ChargeCurrentRequestMax(y),
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


class TeslemetryBluetoothNumberEntity(TeslemetryBluetoothEntity, NumberEntity):
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
        if getattr(data, "poll", False) or not firmware_at_least(
            getattr(data, "firmware", ""), "2024.26"
        ):
            if (coordinator := getattr(data, "coordinator", None)) is not None:
                self._update_max_from_coordinator()
                self.async_on_remove(
                    coordinator.async_add_listener(self._handle_coordinator_update)
                )
        elif self.entity_description.max_listener is not None and (
            stream_vehicle := getattr(data, "stream_vehicle", None)
        ):
            self.async_on_remove(
                self.entity_description.max_listener(
                    stream_vehicle, self._handle_max_update
                )
            )

    def _update_max_from_coordinator(self) -> None:
        """Read the maximum from Teslemetry's vehicle coordinator data."""
        value = self.vehicle.data.coordinator.data.get(self.entity_description.max_key)
        self._attr_native_max_value = (
            value
            if isinstance(value, (int, float))
            else self.entity_description.native_max_value
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the maximum from Teslemetry's vehicle coordinator."""
        self._update_max_from_coordinator()
        self.async_write_ha_state()

    @callback
    def _handle_max_update(self, value: int | None) -> None:
        """Update the maximum from Teslemetry's stream."""
        self._attr_native_max_value = (
            self.entity_description.native_max_value if value is None else value
        )
        self.async_write_ha_state()

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Send the value."""
        await self.vehicle.async_send(
            self.entity_description.key,
            **{self.entity_description.argument: int(value)},
        )

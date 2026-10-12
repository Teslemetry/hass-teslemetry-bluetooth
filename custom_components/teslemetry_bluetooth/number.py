"""Bluetooth-only command numbers for Teslemetry vehicles."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, PRECISION_WHOLE, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
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


# The key of each description is also the Bluetooth command it sends.
DESCRIPTIONS: tuple[TeslemetryBluetoothNumberEntityDescription, ...] = (
    TeslemetryBluetoothNumberEntityDescription(
        key="set_charge_limit",
        argument="percent",
        native_min_value=CHARGE_LIMIT_MIN,
        native_max_value=CHARGE_LIMIT_MAX,
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
    async def async_set_native_value(self, value: float) -> None:
        """Send the value."""
        await self.vehicle.async_send(
            self.entity_description.key,
            **{self.entity_description.argument: int(value)},
        )

"""Bluetooth-only command buttons for Teslemetry vehicles."""

from typing import TYPE_CHECKING, override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 0

# The key of each description is also the Bluetooth command it sends.
DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(key="wake_up"),
    ButtonEntityDescription(key="charge_start"),
    ButtonEntityDescription(key="charge_stop"),
    ButtonEntityDescription(key="door_lock", entity_registry_enabled_default=False),
    ButtonEntityDescription(key="door_unlock", entity_registry_enabled_default=False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    async_add_entities(
        TeslemetryBluetoothButtonEntity(vehicle, description)
        for vehicle in entry.runtime_data.values()
        for description in DESCRIPTIONS
    )


class TeslemetryBluetoothButtonEntity(TeslemetryBluetoothEntity, ButtonEntity):
    """A button that sends one command over Bluetooth."""

    def __init__(
        self,
        vehicle: TeslemetryBluetoothVehicle,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    @override
    async def async_press(self) -> None:
        """Send the command."""
        await self.vehicle.async_send(self.entity_description.key)

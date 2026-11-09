"""Charge on solar state read over Bluetooth for Teslemetry vehicles."""

from typing import TYPE_CHECKING, override

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHARGE_ON_SOLAR_INTERVAL, DOMAIN, TESLEMETRY_DOMAIN
from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 1
SCAN_INTERVAL = CHARGE_ON_SOLAR_INTERVAL

KEY = "charge_on_solar"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    entity_registry = er.async_get(hass)
    entities: list[TeslemetryBluetoothChargeOnSolarEntity] = []
    for vehicle in entry.runtime_data.values():
        # Follow Teslemetry's own charge on solar switch.
        if entity_registry.async_get_entity_id(
            Platform.SWITCH, TESLEMETRY_DOMAIN, f"{vehicle.vin}-{KEY}"
        ):
            entities.append(TeslemetryBluetoothChargeOnSolarEntity(vehicle))
        elif entity_id := entity_registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, f"{vehicle.vin}-bluetooth-{KEY}"
        ):
            entity_registry.async_remove(entity_id)
    async_add_entities(entities)


class TeslemetryBluetoothChargeOnSolarEntity(
    TeslemetryBluetoothEntity, BinarySensorEntity
):
    """Whether charge on solar is on, read over Bluetooth while the car is awake."""

    _attr_should_poll = True
    _attr_entity_registry_enabled_default = False

    def __init__(self, vehicle: TeslemetryBluetoothVehicle) -> None:
        """Initialize the binary sensor."""
        super().__init__(vehicle, KEY)

    @override
    async def async_added_to_hass(self) -> None:
        """Read the car when added."""
        await super().async_added_to_hass()
        self.async_schedule_update_ha_state(True)

    async def async_update(self) -> None:
        """Read charge on solar, keeping the last value if the car is not read."""
        if (enabled := await self.vehicle.async_read_charge_on_solar()) is not None:
            self._attr_is_on = enabled

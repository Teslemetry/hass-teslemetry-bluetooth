"""Base entity for Teslemetry Bluetooth Commands."""

from typing import override

from homeassistant.helpers.entity import Entity

from .vehicle import TeslemetryBluetoothVehicle


class TeslemetryBluetoothEntity(Entity):
    """A command entity on a Teslemetry vehicle device, sent over Bluetooth only."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, vehicle: TeslemetryBluetoothVehicle, key: str) -> None:
        """Initialize the entity."""
        self.vehicle = vehicle
        self._attr_translation_key = key
        self._attr_unique_id = f"{vehicle.vin}-bluetooth-{key}"
        # Attach to Teslemetry's device instead of registering one of our own.
        self.device_entry = vehicle.device

    @property
    @override
    def available(self) -> bool:
        """Return if the vehicle is in Bluetooth range."""
        return self.vehicle.in_range

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the vehicle's in-range state."""
        await super().async_added_to_hass()
        self.async_on_remove(self.vehicle.async_add_listener(self.async_write_ha_state))

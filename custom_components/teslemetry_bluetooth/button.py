"""Bluetooth-only command buttons for Teslemetry vehicles."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api.const import AutoSeat

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TeslemetryBluetoothButtonEntityDescription(ButtonEntityDescription):
    """Describes a button that sends one command over Bluetooth."""

    # The Bluetooth command, when it is not the key.
    command: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    supported_fn: Callable[[TeslemetryBluetoothVehicle], bool] = lambda _: True


def _on_off(
    key: str,
    command: str,
    argument: str,
    supported_fn: Callable[[TeslemetryBluetoothVehicle], bool] = lambda _: True,
    **arguments: Any,
) -> tuple[TeslemetryBluetoothButtonEntityDescription, ...]:
    """Describe an On and an Off button for one of Teslemetry's switches.

    A switch would need the car's state, so each direction is its own button.
    """
    return tuple(
        TeslemetryBluetoothButtonEntityDescription(
            key=f"{key}_{suffix}",
            command=command,
            arguments={**arguments, argument: on},
            supported_fn=supported_fn,
            entity_registry_enabled_default=False,
        )
        for suffix, on in (("on", True), ("off", False))
    )


DESCRIPTIONS: tuple[TeslemetryBluetoothButtonEntityDescription, ...] = (
    TeslemetryBluetoothButtonEntityDescription(key="wake_up"),
    TeslemetryBluetoothButtonEntityDescription(key="charge_start"),
    TeslemetryBluetoothButtonEntityDescription(key="charge_stop"),
    TeslemetryBluetoothButtonEntityDescription(
        key="door_lock", entity_registry_enabled_default=False
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="door_unlock", entity_registry_enabled_default=False
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="media_toggle_playback", entity_registry_enabled_default=False
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="media_next_track", entity_registry_enabled_default=False
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="media_prev_track", entity_registry_enabled_default=False
    ),
    *_on_off("vehicle_state_sentry_mode", "set_sentry_mode", "on"),
    *_on_off("vehicle_state_valet_mode", "set_valet_mode", "on", password=""),
    *_on_off(
        "climate_state_auto_seat_climate_left",
        "remote_auto_seat_climate_request",
        "auto_climate_on",
        auto_seat_position=AutoSeat.FRONT_LEFT,
    ),
    *_on_off(
        "climate_state_auto_seat_climate_right",
        "remote_auto_seat_climate_request",
        "auto_climate_on",
        auto_seat_position=AutoSeat.FRONT_RIGHT,
    ),
    *_on_off(
        "climate_state_auto_steering_wheel_heat",
        "remote_auto_steering_wheel_heat_climate_request",
        "on",
    ),
    *_on_off(
        "climate_state_defrost_mode",
        "set_preconditioning_max",
        "on",
        manual_override=False,
    ),
    # Teslemetry has a Guest mode switch only for streaming vehicles.
    *_on_off(
        "guest_mode_enabled",
        "guest_mode",
        "enable",
        supported_fn=lambda vehicle: vehicle.streaming,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    entity_registry = er.async_get(hass)
    entities: list[TeslemetryBluetoothButtonEntity] = []
    for vehicle in entry.runtime_data.values():
        for description in DESCRIPTIONS:
            if description.supported_fn(vehicle):
                entities.append(TeslemetryBluetoothButtonEntity(vehicle, description))
            # Remove a button the vehicle had before, such as Guest mode on a
            # car that Teslemetry no longer streams.
            elif entity_id := entity_registry.async_get_entity_id(
                Platform.BUTTON, DOMAIN, f"{vehicle.vin}-bluetooth-{description.key}"
            ):
                entity_registry.async_remove(entity_id)
    async_add_entities(entities)


class TeslemetryBluetoothButtonEntity(TeslemetryBluetoothEntity, ButtonEntity):
    """A button that sends one command over Bluetooth."""

    entity_description: TeslemetryBluetoothButtonEntityDescription

    def __init__(
        self,
        vehicle: TeslemetryBluetoothVehicle,
        description: TeslemetryBluetoothButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(vehicle, description.key)
        self.entity_description = description

    @override
    async def async_press(self) -> None:
        """Send the command."""
        description = self.entity_description
        await self.vehicle.async_send(
            description.command or description.key, **description.arguments
        )

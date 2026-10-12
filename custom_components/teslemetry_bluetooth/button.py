"""Bluetooth-only command buttons for Teslemetry vehicles."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api.const import AutoSeat

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.components.button.const import ButtonDeviceClass
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, TESLEMETRY_DOMAIN
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
    # Arguments built when the button is pressed, added to the fixed ones.
    arguments_fn: Callable[[HomeAssistant], Mapping[str, Any]] | None = None
    supported_fn: Callable[[TeslemetryBluetoothVehicle], bool] = lambda _: True
    # Teslemetry's own entity for the same command, as (platform, key). The
    # button is added only where Teslemetry added that entity for the vehicle.
    teslemetry_entity: tuple[Platform, str] | None = None


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
    TeslemetryBluetoothButtonEntityDescription(
        key="flash_lights",
        teslemetry_entity=(Platform.BUTTON, "flash_lights"),
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="honk_horn",
        teslemetry_entity=(Platform.BUTTON, "honk"),
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="remote_boombox",
        arguments={"sound": 0},
        teslemetry_entity=(Platform.BUTTON, "boombox"),
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="trigger_homelink",
        # Like Teslemetry, send the Home Assistant home location.
        arguments_fn=lambda hass: {
            "lat": hass.config.latitude,
            "lon": hass.config.longitude,
        },
        teslemetry_entity=(Platform.BUTTON, "homelink"),
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="remote_start_drive",
        teslemetry_entity=(Platform.BUTTON, "enable_keyless_driving"),
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothButtonEntityDescription(
        key="schedule_software_update",
        # An offset of 0 starts the install now, as Teslemetry's update does.
        arguments={"offset_sec": 0},
        teslemetry_entity=(Platform.UPDATE, "vehicle_state_software_update_status"),
        device_class=ButtonDeviceClass.UPDATE,
        entity_registry_enabled_default=False,
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
            if description.supported_fn(vehicle) and (
                description.teslemetry_entity is None
                or entity_registry.async_get_entity_id(
                    description.teslemetry_entity[0],
                    TESLEMETRY_DOMAIN,
                    f"{vehicle.vin}-{description.teslemetry_entity[1]}",
                )
                is not None
            ):
                entities.append(TeslemetryBluetoothButtonEntity(vehicle, description))
            # Remove a button the vehicle had before, such as Guest mode on a
            # car that Teslemetry no longer streams, or a button whose
            # Teslemetry entity is gone.
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
        arguments = dict(description.arguments)
        if description.arguments_fn is not None:
            arguments.update(description.arguments_fn(self.hass))
        await self.vehicle.async_send(
            description.command or description.key, **arguments
        )

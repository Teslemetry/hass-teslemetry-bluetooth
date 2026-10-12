"""Bluetooth-only command selects for Teslemetry vehicles."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api.const import CabinOverheatProtectionTemp, ClimateKeeperMode, Seat

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, TESLEMETRY_DOMAIN
from .entity import TeslemetryBluetoothEntity
from .vehicle import TeslemetryBluetoothVehicle

if TYPE_CHECKING:
    from . import TeslemetryBluetoothConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TeslemetryBluetoothSelectEntityDescription(SelectEntityDescription):
    """Describes a select that sends one command over Bluetooth."""

    # The Bluetooth command, when it is not the key.
    command: str | None = None
    # The command arguments of each option.
    option_arguments: Mapping[str, Mapping[str, Any]]
    supported_fn: Callable[[TeslemetryBluetoothVehicle], bool] = lambda _: True
    # Teslemetry's own select for the same command. The select is added only
    # where Teslemetry added that entity for the vehicle.
    teslemetry_entity: str | None = None
    # Turn climate on first, as Teslemetry does, for any option but off.
    climate_required: bool = False


# Teslemetry's seat heater and seat cooler levels.
LEVELS = {"off": 0, "low": 1, "medium": 2, "high": 3}


def _seat_heater(key: str, seat: Seat) -> TeslemetryBluetoothSelectEntityDescription:
    """Describe a select for one of Teslemetry's seat heaters."""
    return TeslemetryBluetoothSelectEntityDescription(
        key=key,
        command="remote_seat_heater_request",
        option_arguments={
            option: {"seat_position": seat, "seat_heater_level": level}
            for option, level in LEVELS.items()
        },
        teslemetry_entity=key,
        climate_required=True,
        entity_registry_enabled_default=False,
    )


def _seat_cooler(key: str, position: int) -> TeslemetryBluetoothSelectEntityDescription:
    """Describe a select for one of Teslemetry's seat coolers."""
    return TeslemetryBluetoothSelectEntityDescription(
        key=key,
        command="remote_seat_cooler_request",
        # The cooler positions count from 1: front left is 1, front right is 2.
        option_arguments={
            option: {"seat_position": position, "seat_cooler_level": level}
            for option, level in LEVELS.items()
        },
        teslemetry_entity=key,
        climate_required=True,
        entity_registry_enabled_default=False,
    )


# The key of each description is also the Bluetooth command it sends, unless
# the description names its command.
DESCRIPTIONS: tuple[TeslemetryBluetoothSelectEntityDescription, ...] = (
    TeslemetryBluetoothSelectEntityDescription(
        key="set_climate_keeper_mode",
        option_arguments={
            "off": {"climate_keeper_mode": ClimateKeeperMode.OFF},
            "keep": {"climate_keeper_mode": ClimateKeeperMode.KEEP_MODE},
            "dog": {"climate_keeper_mode": ClimateKeeperMode.DOG_MODE},
            "camp": {"climate_keeper_mode": ClimateKeeperMode.CAMP_MODE},
        },
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothSelectEntityDescription(
        key="set_cabin_overheat_protection",
        option_arguments={
            "off": {"on": False, "fan_only": False},
            "on": {"on": True, "fan_only": False},
            "fan_only": {"on": True, "fan_only": True},
        },
        entity_registry_enabled_default=False,
    ),
    TeslemetryBluetoothSelectEntityDescription(
        key="set_cop_temp",
        option_arguments={
            "low": {"cop_temp": CabinOverheatProtectionTemp.LOW},
            "medium": {"cop_temp": CabinOverheatProtectionTemp.MEDIUM},
            "high": {"cop_temp": CabinOverheatProtectionTemp.HIGH},
        },
        supported_fn=lambda vehicle: vehicle.cop_temperature_supported,
        entity_registry_enabled_default=False,
    ),
    _seat_heater("climate_state_seat_heater_left", Seat.FRONT_LEFT),
    _seat_heater("climate_state_seat_heater_right", Seat.FRONT_RIGHT),
    _seat_heater("climate_state_seat_heater_rear_left", Seat.REAR_LEFT),
    _seat_heater("climate_state_seat_heater_rear_center", Seat.REAR_CENTER),
    _seat_heater("climate_state_seat_heater_rear_right", Seat.REAR_RIGHT),
    _seat_heater("climate_state_seat_heater_third_row_left", Seat.THIRD_LEFT),
    _seat_heater("climate_state_seat_heater_third_row_right", Seat.THIRD_RIGHT),
    TeslemetryBluetoothSelectEntityDescription(
        key="climate_state_steering_wheel_heat_level",
        command="remote_steering_wheel_heat_level_request",
        # The steering wheel has no medium level.
        option_arguments={
            "off": {"level": 0},
            "low": {"level": 1},
            "high": {"level": 3},
        },
        teslemetry_entity="climate_state_steering_wheel_heat_level",
        climate_required=True,
        entity_registry_enabled_default=False,
    ),
    _seat_cooler("climate_state_seat_fan_front_left", 1),
    _seat_cooler("climate_state_seat_fan_front_right", 2),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryBluetoothConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    entity_registry = er.async_get(hass)
    entities: list[TeslemetryBluetoothSelectEntity] = []
    for vehicle in entry.runtime_data.values():
        for description in DESCRIPTIONS:
            if description.supported_fn(vehicle) and (
                description.teslemetry_entity is None
                or entity_registry.async_get_entity_id(
                    Platform.SELECT,
                    TESLEMETRY_DOMAIN,
                    f"{vehicle.vin}-{description.teslemetry_entity}",
                )
                is not None
            ):
                entities.append(TeslemetryBluetoothSelectEntity(vehicle, description))
            # Remove a select the vehicle had before, such as the cabin
            # overheat protection temperature on a car that no longer has it,
            # or a select whose Teslemetry entity is gone.
            elif entity_id := entity_registry.async_get_entity_id(
                Platform.SELECT, DOMAIN, f"{vehicle.vin}-bluetooth-{description.key}"
            ):
                entity_registry.async_remove(entity_id)
    async_add_entities(entities)


class TeslemetryBluetoothSelectEntity(TeslemetryBluetoothEntity, SelectEntity):
    """A select that sends the chosen option over Bluetooth.

    It has no state: the current option stays on Teslemetry's own entity.
    """

    entity_description: TeslemetryBluetoothSelectEntityDescription
    _attr_current_option = None
    # The climate state from Teslemetry's stream, if the select needs it. Like
    # Teslemetry's own selects, it counts as off until the stream sends it, so
    # the first level after a restart can turn climate on when it is already on.
    _climate_on = False

    def __init__(
        self,
        vehicle: TeslemetryBluetoothVehicle,
        description: TeslemetryBluetoothSelectEntityDescription,
    ) -> None:
        """Initialize the select."""
        super().__init__(vehicle, description.key)
        self.entity_description = description
        self._attr_options = list(description.option_arguments)

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the car's climate state from Teslemetry's stream."""
        await super().async_added_to_hass()
        if not self.entity_description.climate_required or not self.vehicle.streaming:
            return
        # Listen on the stream itself: the vehicle's listen_* helpers enable the
        # field in the vehicle's streaming config through the cloud. An internal
        # listener also never opens or holds the stream connection by itself.
        self.async_on_remove(
            self.vehicle.data.stream_vehicle.stream.async_add_listener(
                self._handle_climate_update,
                {"vin": self.vehicle.vin, "data": {"HvacPower": None}},
                internal=True,
            )
        )

    @callback
    def _handle_climate_update(self, event: dict[str, Any]) -> None:
        """Store whether the stream shows climate on."""
        value = event["data"]["HvacPower"]
        # The same states Teslemetry's own selects count as climate on.
        self._climate_on = isinstance(value, str) and value.removeprefix(
            "HvacPowerState"
        ) in ("On", "Precondition")

    def _climate_is_on(self) -> bool:
        """Return if Teslemetry's data shows the car's climate on."""
        # Teslemetry's selects read a polled car from its vehicle coordinator.
        if not self.vehicle.streaming:
            return bool(
                self.vehicle.data.coordinator.data.get("climate_state_is_climate_on")
            )
        return self._climate_on

    @override
    async def async_select_option(self, option: str) -> None:
        """Send the option."""
        description = self.entity_description
        # Teslemetry turns climate on before it sets a level above off.
        if (
            description.climate_required
            and option != "off"
            and not self._climate_is_on()
        ):
            await self.vehicle.async_send("auto_conditioning_start")
        await self.vehicle.async_send(
            description.command or description.key,
            **description.option_arguments[option],
        )

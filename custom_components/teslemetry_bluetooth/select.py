"""Bluetooth-only command selects for Teslemetry vehicles."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from tesla_fleet_api.const import CabinOverheatProtectionTemp, ClimateKeeperMode

from homeassistant.components.select import SelectEntity, SelectEntityDescription
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
class TeslemetryBluetoothSelectEntityDescription(SelectEntityDescription):
    """Describes a select that sends one command over Bluetooth."""

    # The command arguments of each option.
    option_arguments: Mapping[str, Mapping[str, Any]]
    supported_fn: Callable[[TeslemetryBluetoothVehicle], bool] = lambda _: True


# The key of each description is also the Bluetooth command it sends.
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
            if description.supported_fn(vehicle):
                entities.append(TeslemetryBluetoothSelectEntity(vehicle, description))
            # Remove a select the vehicle had before, such as the cabin
            # overheat protection temperature on a car that no longer has it.
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
    async def async_select_option(self, option: str) -> None:
        """Send the option."""
        await self.vehicle.async_send(
            self.entity_description.key,
            **self.entity_description.option_arguments[option],
        )

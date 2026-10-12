"""Teslemetry Bluetooth Commands: Bluetooth-only commands for Teslemetry vehicles."""

from datetime import datetime
from typing import Any, Final

from tesla_fleet_api.router import VehicleRouter

from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    issue_registry as ir,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .const import (
    COMMANDS,
    DOMAIN,
    ISSUE_INCOMPATIBLE_TESLEMETRY,
    LOGGER,
    MIN_TESLEMETRY_VERSION,
    RANGE_CHECK_INTERVAL,
    TESLEMETRY_DOMAIN,
)
from .services import async_setup_services
from .vehicle import TeslemetryBluetoothVehicle

PLATFORMS: Final = [Platform.BUTTON, Platform.NUMBER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TeslemetryBluetoothConfigEntry = ConfigEntry[dict[str, TeslemetryBluetoothVehicle]]


class IncompatibleTeslemetry(Exception):
    """Teslemetry does not expose the Bluetooth runtime this integration needs."""


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    async_setup_services(hass)
    return True


def _bluetooth_vehicles(hass: HomeAssistant) -> dict[str, TeslemetryBluetoothVehicle]:
    """Return the Bluetooth-paired vehicles of every loaded Teslemetry entry."""
    device_registry = dr.async_get(hass)
    vehicles: dict[str, TeslemetryBluetoothVehicle] = {}
    for teslemetry_entry in hass.config_entries.async_loaded_entries(TESLEMETRY_DOMAIN):
        runtime = getattr(teslemetry_entry, "runtime_data", None)
        if (vehicle_list := getattr(runtime, "vehicles", None)) is None:
            raise IncompatibleTeslemetry("runtime_data.vehicles")
        for vehicle_data in vehicle_list:
            for attr in ("api", "vin"):
                if not hasattr(vehicle_data, attr):
                    raise IncompatibleTeslemetry(f"vehicle.{attr}")
            api = vehicle_data.api
            # Teslemetry gives a vehicle a VehicleRouter only when it is paired
            # over Bluetooth and its key loaded; any other vehicle is cloud only.
            if not isinstance(api, VehicleRouter):
                continue
            if not callable(getattr(api, "is_healthy", None)):
                raise IncompatibleTeslemetry("VehicleRouter.is_healthy")
            primary = api.primary
            for command in COMMANDS:
                if not callable(getattr(primary, command, None)):
                    raise IncompatibleTeslemetry(f"Bluetooth vehicle.{command}")
            device = device_registry.async_get_device_by_identifier(
                (TESLEMETRY_DOMAIN, vehicle_data.vin), teslemetry_entry.entry_id
            )
            if device is None:
                LOGGER.warning(
                    "Teslemetry has no device for vehicle %s", vehicle_data.vin
                )
                continue
            vehicles[vehicle_data.vin] = TeslemetryBluetoothVehicle(
                api, vehicle_data.vin, device
            )
    return vehicles


def _teslemetry_snapshot(hass: HomeAssistant) -> dict[str, int]:
    """Identify each loaded Teslemetry entry's runtime data."""
    return {
        teslemetry_entry.entry_id: id(getattr(teslemetry_entry, "runtime_data", None))
        for teslemetry_entry in hass.config_entries.async_loaded_entries(
            TESLEMETRY_DOMAIN
        )
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: TeslemetryBluetoothConfigEntry
) -> bool:
    """Set up Teslemetry Bluetooth Commands from a config entry."""
    try:
        vehicles = _bluetooth_vehicles(hass)
    except IncompatibleTeslemetry as err:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_INCOMPATIBLE_TESLEMETRY,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_INCOMPATIBLE_TESLEMETRY,
            translation_placeholders={
                "version": MIN_TESLEMETRY_VERSION,
                "missing": str(err),
            },
        )
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key=ISSUE_INCOMPATIBLE_TESLEMETRY,
            translation_placeholders={
                "version": MIN_TESLEMETRY_VERSION,
                "missing": str(err),
            },
        ) from err
    ir.async_delete_issue(hass, DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)
    LOGGER.debug("Bluetooth-paired Teslemetry vehicles: %s", list(vehicles))

    for vehicle in vehicles.values():
        await vehicle.async_update_range()
    entry.runtime_data = vehicles

    async def _async_update_range(_: datetime) -> None:
        for vehicle in vehicles.values():
            await vehicle.async_update_range()

    entry.async_on_unload(
        async_track_time_interval(
            hass, _async_update_range, RANGE_CHECK_INTERVAL, cancel_on_shutdown=True
        )
    )

    # The vehicle objects belong to Teslemetry's runtime data, so reload
    # whenever a Teslemetry entry loads, unloads or reloads.
    snapshot = _teslemetry_snapshot(hass)

    @callback
    def _async_teslemetry_changed(change: ConfigEntryChange, changed: Any) -> None:
        if changed.domain != TESLEMETRY_DOMAIN:
            return
        if _teslemetry_snapshot(hass) != snapshot:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_CONFIG_ENTRY_CHANGED, _async_teslemetry_changed
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TeslemetryBluetoothConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: TeslemetryBluetoothConfigEntry
) -> None:
    """Remove the repair issue with the entry."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)

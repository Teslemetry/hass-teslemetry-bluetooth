"""Tests for the Teslemetry Bluetooth Commands buttons."""

import inspect
from typing import Any

from bleak.exc import BleakError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tesla_fleet_api.const import AutoSeat
from tesla_fleet_api.tesla.vehicle.bluetooth import VehicleBluetooth

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import (
    CLOSE_SUNROOF,
    CLOSE_TONNEAU,
    COVER_BUTTONS,
    OPEN_TONNEAU,
    STOP_TONNEAU,
    VENT_SUNROOF,
    VENT_WINDOWS,
    VIN,
    FakeTeslemetry,
    setup_integration,
)

GUEST_MODE_ON = "button.test_car_guest_mode_on_bluetooth"
GUEST_MODE_OFF = "button.test_car_guest_mode_off_bluetooth"
SUNROOF_BUTTONS = (VENT_SUNROOF, CLOSE_SUNROOF)
TONNEAU_BUTTONS = (OPEN_TONNEAU, CLOSE_TONNEAU, STOP_TONNEAU)

# (button, Bluetooth command, command kwargs) for each switch's On and Off.
SWITCH_BUTTONS = [
    ("sentry_mode_on", "set_sentry_mode", {"on": True}),
    ("sentry_mode_off", "set_sentry_mode", {"on": False}),
    ("valet_mode_on", "set_valet_mode", {"on": True, "password": ""}),
    ("valet_mode_off", "set_valet_mode", {"on": False, "password": ""}),
    (
        "auto_seat_climate_left_on",
        "remote_auto_seat_climate_request",
        {"auto_seat_position": AutoSeat.FRONT_LEFT, "auto_climate_on": True},
    ),
    (
        "auto_seat_climate_left_off",
        "remote_auto_seat_climate_request",
        {"auto_seat_position": AutoSeat.FRONT_LEFT, "auto_climate_on": False},
    ),
    (
        "auto_seat_climate_right_on",
        "remote_auto_seat_climate_request",
        {"auto_seat_position": AutoSeat.FRONT_RIGHT, "auto_climate_on": True},
    ),
    (
        "auto_seat_climate_right_off",
        "remote_auto_seat_climate_request",
        {"auto_seat_position": AutoSeat.FRONT_RIGHT, "auto_climate_on": False},
    ),
    (
        "auto_steering_wheel_heater_on",
        "remote_auto_steering_wheel_heat_climate_request",
        {"on": True},
    ),
    (
        "auto_steering_wheel_heater_off",
        "remote_auto_steering_wheel_heat_climate_request",
        {"on": False},
    ),
    ("defrost_on", "set_preconditioning_max", {"on": True, "manual_override": False}),
    (
        "defrost_off",
        "set_preconditioning_max",
        {"on": False, "manual_override": False},
    ),
    ("guest_mode_on", "guest_mode", {"enable": True}),
    ("guest_mode_off", "guest_mode", {"enable": False}),
]


def _entity_id(name: str) -> str:
    """Return the entity id of a Bluetooth button on the test car."""
    return f"button.test_car_{name}_bluetooth"


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    """Press a button."""
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_switch_buttons_disabled(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Each switch's On and Off buttons are disabled by default."""
    await setup_integration(hass)

    for name, *_ in SWITCH_BUTTONS:
        entry = entity_registry.async_get(_entity_id(name))
        assert entry is not None, name
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
@pytest.mark.parametrize(("name", "command", "kwargs"), SWITCH_BUTTONS)
async def test_switch_button_press(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    name: str,
    command: str,
    kwargs: dict[str, Any],
) -> None:
    """Each switch button sends its command over Bluetooth only."""
    await setup_integration(hass)

    # The library's Bluetooth vehicle accepts these arguments.
    inspect.signature(getattr(VehicleBluetooth, command)).bind(None, **kwargs)

    await _press(hass, _entity_id(name))
    getattr(teslemetry.bluetooth, command).assert_awaited_once_with(**kwargs)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_switch_button_out_of_range(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """Out of range, a switch button fails, sends nothing and is unavailable."""
    await setup_integration(hass)

    # The car leaves range before the next check: the press fails.
    teslemetry.in_range = False
    with pytest.raises(HomeAssistantError) as exc:
        await _press(hass, _entity_id("sentry_mode_on"))
    assert exc.value.translation_key == "not_in_range"
    for name, *_ in SWITCH_BUTTONS:
        assert hass.states.get(_entity_id(name)).state == STATE_UNAVAILABLE
    teslemetry.bluetooth.set_sentry_mode.assert_not_awaited()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
@pytest.mark.parametrize(
    ("result", "error", "translation_key"),
    [
        pytest.param(None, BleakError("disconnected"), "bluetooth_failed", id="error"),
        pytest.param(
            {"response": {"result": False, "reason": "user_present"}},
            None,
            "command_failed",
            id="refused",
        ),
    ],
)
async def test_switch_button_failure(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    result: dict[str, Any] | None,
    error: BaseException | None,
    translation_key: str,
) -> None:
    """A failed switch command raises an error and never reaches the cloud."""
    await setup_integration(hass)
    teslemetry.bluetooth.set_valet_mode.return_value = result
    teslemetry.bluetooth.set_valet_mode.side_effect = error

    with pytest.raises(HomeAssistantError) as exc:
        await _press(hass, _entity_id("valet_mode_off"))
    assert exc.value.translation_key == translation_key
    teslemetry.bluetooth.set_valet_mode.assert_awaited_once_with(on=False, password="")
    teslemetry.assert_cloud_unused()


@pytest.mark.parametrize(
    ("poll", "firmware", "created"),
    [
        pytest.param(False, "2026.20.1", True, id="streaming"),
        pytest.param(True, "2026.20.1", False, id="polling"),
        pytest.param(False, "2024.20.9", False, id="old_firmware"),
    ],
)
@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_guest_mode_streaming_only(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    poll: bool,
    firmware: str,
    created: bool,
) -> None:
    """Guest mode buttons exist only where Teslemetry has its Guest mode switch."""
    teslemetry.poll = poll
    teslemetry.firmware = firmware
    await setup_integration(hass)

    for entity_id in (GUEST_MODE_ON, GUEST_MODE_OFF):
        assert (entity_registry.async_get(entity_id) is not None) is created
    # Teslemetry has every other switch for every vehicle.
    assert entity_registry.async_get(_entity_id("sentry_mode_on")) is not None


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_guest_mode_removed_when_polled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Guest mode buttons go when Teslemetry stops streaming the car."""
    await setup_integration(hass)
    assert entity_registry.async_get(GUEST_MODE_ON) is not None

    # Teslemetry reloads with the car polled; this integration reloads too.
    teslemetry.poll = True
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in (GUEST_MODE_ON, GUEST_MODE_OFF):
        assert entity_registry.async_get(entity_id) is None
        assert hass.states.get(entity_id) is None
    assert hass.states.get(_entity_id("sentry_mode_on")) is not None
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
@pytest.mark.parametrize(
    ("cover_keys", "added", "missing"),
    [
        pytest.param(
            ["vehicle_state_sun_roof_state"],
            SUNROOF_BUTTONS,
            TONNEAU_BUTTONS,
            id="sunroof",
        ),
        pytest.param(["tonneau"], TONNEAU_BUTTONS, SUNROOF_BUTTONS, id="tonneau"),
        pytest.param([], (), SUNROOF_BUTTONS + TONNEAU_BUTTONS, id="neither"),
    ],
)
async def test_feature_buttons_follow_teslemetry_covers(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    cover_keys: list[str],
    added: tuple[str, ...],
    missing: tuple[str, ...],
) -> None:
    """The sunroof and tonneau buttons exist only if Teslemetry has the cover."""
    teslemetry.entities = tuple(("cover", key) for key in cover_keys)
    await setup_integration(hass)

    for entity_id in added:
        assert entity_registry.async_get(entity_id) is not None, entity_id
    for entity_id in missing:
        assert entity_registry.async_get(entity_id) is None, entity_id
    # The buttons every vehicle has do not depend on a cover.
    assert entity_registry.async_get(VENT_WINDOWS) is not None
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
@pytest.mark.parametrize(
    ("entity_id", "command"),
    [(entity_id, command) for entity_id, command, _ in COVER_BUTTONS],
)
async def test_cover_button_refused(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    entity_id: str,
    command: str,
) -> None:
    """A refused cover command raises an error and never reaches the cloud."""
    await setup_integration(hass)
    getattr(teslemetry.bluetooth, command).return_value = {
        "response": {"result": False, "reason": "GENERICERROR_CLOSURES_OPEN"}
    }

    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
    assert exc.value.translation_key == "command_failed"
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("config_entry")
async def test_feature_buttons_removed_with_cover(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
) -> None:
    """The tonneau buttons go when Teslemetry's Tonneau cover is removed."""
    await setup_integration(hass)
    assert entity_registry.async_get(OPEN_TONNEAU) is not None

    # Teslemetry no longer has the cover; this integration reloads with it.
    cover = entity_registry.async_get_entity_id("cover", "teslemetry", f"{VIN}-tonneau")
    assert cover is not None
    entity_registry.async_remove(cover)
    teslemetry.entities = (("cover", "vehicle_state_sun_roof_state"),)
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in TONNEAU_BUTTONS:
        assert entity_registry.async_get(entity_id) is None
    assert entity_registry.async_get(VENT_SUNROOF) is not None
    teslemetry.assert_cloud_unused()

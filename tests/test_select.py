"""Tests for the Teslemetry Bluetooth Commands seat and steering wheel selects."""

from typing import Any
from unittest.mock import call

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tesla_fleet_api.const import Seat
from tesla_fleet_api.exceptions import BluetoothTimeout

from homeassistant.components.select import ATTR_OPTIONS, DOMAIN as SELECT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import VIN, FakeTeslemetry, setup_integration

HEATER_LEFT = "select.test_car_seat_heater_front_left_bluetooth"
HEATER_RIGHT = "select.test_car_seat_heater_front_right_bluetooth"
STEERING_WHEEL = "select.test_car_steering_wheel_heater_bluetooth"
COOLER_LEFT = "select.test_car_seat_cooler_front_left_bluetooth"

LEVELS = ["off", "low", "medium", "high"]

# (entity, options, chosen option, Bluetooth command, command kwargs)
SELECTS: list[tuple[str, list[str], str, str, dict[str, Any]]] = [
    (
        HEATER_LEFT,
        LEVELS,
        "high",
        "remote_seat_heater_request",
        {"seat_position": Seat.FRONT_LEFT, "seat_heater_level": 3},
    ),
    (
        HEATER_RIGHT,
        LEVELS,
        "low",
        "remote_seat_heater_request",
        {"seat_position": Seat.FRONT_RIGHT, "seat_heater_level": 1},
    ),
    (
        "select.test_car_seat_heater_rear_left_bluetooth",
        LEVELS,
        "medium",
        "remote_seat_heater_request",
        {"seat_position": Seat.REAR_LEFT, "seat_heater_level": 2},
    ),
    (
        "select.test_car_seat_heater_rear_center_bluetooth",
        LEVELS,
        "high",
        "remote_seat_heater_request",
        {"seat_position": Seat.REAR_CENTER, "seat_heater_level": 3},
    ),
    (
        "select.test_car_seat_heater_rear_right_bluetooth",
        LEVELS,
        "low",
        "remote_seat_heater_request",
        {"seat_position": Seat.REAR_RIGHT, "seat_heater_level": 1},
    ),
    (
        "select.test_car_seat_heater_third_row_left_bluetooth",
        LEVELS,
        "high",
        "remote_seat_heater_request",
        {"seat_position": Seat.THIRD_LEFT, "seat_heater_level": 3},
    ),
    (
        "select.test_car_seat_heater_third_row_right_bluetooth",
        LEVELS,
        "medium",
        "remote_seat_heater_request",
        {"seat_position": Seat.THIRD_RIGHT, "seat_heater_level": 2},
    ),
    (
        STEERING_WHEEL,
        ["off", "low", "high"],
        "high",
        "remote_steering_wheel_heat_level_request",
        {"level": 3},
    ),
    (
        COOLER_LEFT,
        LEVELS,
        "high",
        "remote_seat_cooler_request",
        {"seat_position": 1, "seat_cooler_level": 3},
    ),
    (
        "select.test_car_seat_cooler_front_right_bluetooth",
        LEVELS,
        "low",
        "remote_seat_cooler_request",
        {"seat_position": 2, "seat_cooler_level": 1},
    ),
]


async def _select(hass: HomeAssistant, entity_id: str, option: str) -> None:
    """Choose an option."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )


@pytest.mark.parametrize(
    ("entity_id", "options", "option", "command", "kwargs"), SELECTS
)
@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_selects(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    entity_id: str,
    options: list[str],
    option: str,
    command: str,
    kwargs: dict[str, Any],
) -> None:
    """Each select sends its level over Bluetooth and shows no state."""
    teslemetry.poll = True
    teslemetry.coordinator.data = {"climate_state_is_climate_on": True}
    await setup_integration(hass)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_OPTIONS] == options

    await _select(hass, entity_id, option)
    # Climate is already on, so only the level is sent.
    assert teslemetry.bluetooth.mock_calls == [getattr(call, command)(**kwargs)]
    # The state stays on Teslemetry's own entity.
    assert hass.states.get(entity_id).state == STATE_UNKNOWN
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_disabled_by_default(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """The selects are disabled by default."""
    await setup_integration(hass)

    for entity_id, *_ in SELECTS:
        entry = entity_registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_selects_follow_teslemetry_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    config_entry: MockConfigEntry,
    teslemetry: FakeTeslemetry,
) -> None:
    """A select is added only where Teslemetry added the same select."""
    teslemetry.entities = (
        ("select", "climate_state_seat_heater_left"),
        ("select", "climate_state_seat_heater_right"),
        ("select", "climate_state_steering_wheel_heat_level"),
    )
    await setup_integration(hass)

    present = {HEATER_LEFT, HEATER_RIGHT, STEERING_WHEEL}
    for entity_id, *_ in SELECTS:
        assert (hass.states.get(entity_id) is not None) is (entity_id in present)

    # Teslemetry removes its select: the Bluetooth select goes with it.
    teslemetry_entity = entity_registry.async_get_entity_id(
        SELECT_DOMAIN, "teslemetry", f"{VIN}-climate_state_steering_wheel_heat_level"
    )
    assert teslemetry_entity is not None
    entity_registry.async_remove(teslemetry_entity)
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(STEERING_WHEEL) is None
    assert entity_registry.async_get(HEATER_LEFT) is not None
    teslemetry.assert_cloud_unused()


@pytest.mark.parametrize(
    ("vehicle_data", "option", "expected"),
    [
        pytest.param(
            {"climate_state_is_climate_on": False},
            "high",
            [call.auto_conditioning_start()],
            id="off-high",
        ),
        pytest.param({}, "low", [call.auto_conditioning_start()], id="unknown-low"),
        pytest.param({"climate_state_is_climate_on": True}, "high", [], id="on-high"),
        pytest.param({"climate_state_is_climate_on": False}, "off", [], id="off-off"),
    ],
)
@pytest.mark.parametrize(
    ("poll", "firmware"),
    [
        pytest.param(True, "2026.20.1", id="polling"),
        pytest.param(False, "2024.20.1", id="old_firmware"),
    ],
)
@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_climate_first_polling(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    poll: bool,
    firmware: str,
    vehicle_data: dict[str, bool],
    option: str,
    expected: list[Any],
) -> None:
    """A polled car turns climate on first if Teslemetry's coordinator shows it off."""
    teslemetry.poll = poll
    teslemetry.firmware = firmware
    teslemetry.coordinator.data = vehicle_data
    await setup_integration(hass)
    # The coordinator is read when the option is chosen; the stream is unused.
    assert teslemetry.stream.listeners == []

    await _select(hass, HEATER_LEFT, option)
    seat_call = call.remote_seat_heater_request(
        seat_position=Seat.FRONT_LEFT, seat_heater_level=LEVELS.index(option)
    )
    assert teslemetry.bluetooth.mock_calls == [*expected, seat_call]
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_climate_first_streaming(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """A streaming car turns climate on first unless HvacPower shows it on."""
    # A streaming car's climate is never read from the coordinator.
    teslemetry.coordinator.data = {"climate_state_is_climate_on": True}
    await setup_integration(hass)
    # Passive listeners: they never open or hold the stream by themselves.
    assert teslemetry.stream.listeners
    assert all(internal for _, _, internal in teslemetry.stream.listeners)
    start = teslemetry.bluetooth.auto_conditioning_start

    # Unknown until the stream sends it.
    await _select(hass, COOLER_LEFT, "high")
    assert start.await_count == 1

    for value, starts in (
        ("On", 0),
        ("Off", 1),
        ("HvacPowerStatePrecondition", 0),
        ("OverheatProtect", 1),
        (None, 1),
    ):
        start.reset_mock()
        teslemetry.stream.send({"HvacPower": value})
        await _select(hass, COOLER_LEFT, "low")
        assert start.await_count == starts, value
    teslemetry.bluetooth.remote_seat_cooler_request.assert_awaited_with(
        seat_position=1, seat_cooler_level=1
    )
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_select_errors(hass: HomeAssistant, teslemetry: FakeTeslemetry) -> None:
    """A select raises the same errors as the other entities."""
    await setup_integration(hass)
    command = teslemetry.bluetooth.remote_seat_heater_request
    start = teslemetry.bluetooth.auto_conditioning_start

    # Climate does not turn on: the level is not sent.
    start.side_effect = BluetoothTimeout()
    with pytest.raises(HomeAssistantError) as exc:
        await _select(hass, HEATER_LEFT, "high")
    assert exc.value.translation_key == "bluetooth_failed"
    command.assert_not_awaited()

    start.side_effect = None
    start.return_value = {"response": {"result": False, "reason": "busy"}}
    with pytest.raises(HomeAssistantError) as exc:
        await _select(hass, HEATER_LEFT, "high")
    assert exc.value.translation_key == "command_failed"
    command.assert_not_awaited()

    command.return_value = {"response": {"result": False, "reason": "busy"}}
    with pytest.raises(HomeAssistantError) as exc:
        await _select(hass, HEATER_LEFT, "off")
    assert exc.value.translation_key == "command_failed"
    assert command.await_count == 1

    teslemetry.in_range = False
    with pytest.raises(HomeAssistantError) as exc:
        await _select(hass, HEATER_LEFT, "off")
    assert exc.value.translation_key == "not_in_range"
    assert command.await_count == 1
    assert hass.states.get(HEATER_LEFT).state == STATE_UNAVAILABLE
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_stream_listeners_removed_on_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, teslemetry: FakeTeslemetry
) -> None:
    """Unloading removes the climate listeners from Teslemetry's stream."""
    await setup_integration(hass)
    assert teslemetry.stream.listeners

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert teslemetry.stream.listeners == []

"""Tests for the Teslemetry Bluetooth Commands climate entities."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tesla_fleet_api.exceptions import BluetoothTimeout

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import ATTR_OPTIONS, DOMAIN as SELECT_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeTeslemetry, setup_integration

BIOWEAPON_ON = "button.test_car_bioweapon_defense_on_bluetooth"
BIOWEAPON_OFF = "button.test_car_bioweapon_defense_off_bluetooth"
TARGET_TEMPERATURE = "number.test_car_target_temperature_bluetooth"
CLIMATE_KEEPER = "select.test_car_climate_keeper_mode_bluetooth"
COP = "select.test_car_cabin_overheat_protection_bluetooth"
COP_TEMPERATURE = "select.test_car_cabin_overheat_protection_temperature_bluetooth"

POLLED_CLIMATE = [
    pytest.param(True, "2026.20.1", id="polling"),
    pytest.param(False, "2024.44.20", id="old_firmware"),
]


def _limits(hass: HomeAssistant, entity_id: str) -> tuple[float, float]:
    """Return the min and max of a number."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state.attributes[ATTR_MIN], state.attributes[ATTR_MAX]


@pytest.mark.parametrize(("poll", "firmware"), POLLED_CLIMATE)
@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_bioweapon_defense(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, poll: bool, firmware: str
) -> None:
    """A car whose climate Teslemetry polls has the bioweapon defense buttons."""
    teslemetry.poll = poll
    teslemetry.firmware = firmware
    await setup_integration(hass)

    for entity_id, on in ((BIOWEAPON_ON, True), (BIOWEAPON_OFF, False)):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )
        teslemetry.bluetooth.set_bioweapon_mode.assert_awaited_once_with(
            on=on, manual_override=True
        )
        teslemetry.bluetooth.set_bioweapon_mode.reset_mock()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_bioweapon_defense_streaming(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A car whose climate Teslemetry streams has no bioweapon defense buttons."""
    await setup_integration(hass)

    assert entity_registry.async_get(BIOWEAPON_ON) is None
    assert entity_registry.async_get(BIOWEAPON_OFF) is None


@pytest.mark.parametrize(
    ("poll", "config", "vehicle_data", "supported"),
    [
        pytest.param(
            False,
            {"cop_user_set_temp_supported": True},
            {},
            True,
            id="streaming-supported",
        ),
        pytest.param(
            False,
            {"cop_user_set_temp_supported": False},
            {},
            False,
            id="streaming-unsupported",
        ),
        pytest.param(False, {}, {}, False, id="streaming-no_config"),
        pytest.param(
            True,
            {},
            {"vehicle_config_cop_user_set_temp_supported": True},
            True,
            id="polling-supported",
        ),
        pytest.param(
            True,
            {"cop_user_set_temp_supported": True},
            {"vehicle_config_cop_user_set_temp_supported": False},
            False,
            id="polling-unsupported",
        ),
    ],
)
@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_cop_temperature_gating(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    poll: bool,
    config: dict[str, bool],
    vehicle_data: dict[str, bool],
    supported: bool,
) -> None:
    """The temperature select exists only if Teslemetry offers the temperature."""
    teslemetry.poll = poll
    teslemetry.config = config
    teslemetry.coordinator.data = vehicle_data
    await setup_integration(hass)

    assert (entity_registry.async_get(COP_TEMPERATURE) is not None) is supported
    # The mode select does not depend on it.
    assert entity_registry.async_get(COP) is not None


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_cop_temperature_old_firmware(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, teslemetry: FakeTeslemetry
) -> None:
    """Old firmware reads the temperature support from the vehicle coordinator."""
    teslemetry.firmware = "2024.44.20"
    teslemetry.config = {}
    teslemetry.coordinator.data = {"vehicle_config_cop_user_set_temp_supported": True}
    await setup_integration(hass)

    assert entity_registry.async_get(COP_TEMPERATURE) is not None


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param({"vehicles": {}}, id="vehicle_missing"),
        pytest.param(None, id="no_data"),
    ],
)
@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_cop_temperature_no_metadata(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    metadata: dict[str, dict[str, str]] | None,
) -> None:
    """A streaming car without metadata has no temperature select."""
    teslemetry.runtime_data = teslemetry.build_runtime_data()
    teslemetry.runtime_data.metadata_coordinator.data = metadata
    await setup_integration(hass)

    assert entity_registry.async_get(COP_TEMPERATURE) is None
    assert entity_registry.async_get(COP) is not None


@pytest.mark.usefixtures("teslemetry_entry")
async def test_unsupported_entities_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
) -> None:
    """Entities the car no longer supports are removed on reload."""
    teslemetry.poll = True
    teslemetry.coordinator.data = {"vehicle_config_cop_user_set_temp_supported": True}
    await setup_integration(hass)
    assert entity_registry.async_get(BIOWEAPON_ON) is not None
    assert entity_registry.async_get(COP_TEMPERATURE) is not None

    # Teslemetry now streams the car, which has no temperature support.
    teslemetry.poll = False
    teslemetry.config = {}
    (teslemetry_entry,) = hass.config_entries.async_entries("teslemetry")
    teslemetry_entry.runtime_data = teslemetry.build_runtime_data()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(BIOWEAPON_ON) is None
    assert entity_registry.async_get(COP_TEMPERATURE) is None
    assert entity_registry.async_get(COP) is not None


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_selects(hass: HomeAssistant, teslemetry: FakeTeslemetry) -> None:
    """The selects show no state and offer Teslemetry's options."""
    await setup_integration(hass)

    for entity_id, options in (
        (CLIMATE_KEEPER, ["off", "keep", "dog", "camp"]),
        (COP, ["off", "on", "fan_only"]),
        (COP_TEMPERATURE, ["low", "medium", "high"]),
    ):
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == STATE_UNKNOWN
        assert state.attributes[ATTR_OPTIONS] == options

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: COP, ATTR_OPTION: "off"},
        blocking=True,
    )
    teslemetry.bluetooth.set_cabin_overheat_protection.assert_awaited_once_with(
        on=False, fan_only=False
    )
    # The state stays on Teslemetry's own entity.
    assert hass.states.get(COP).state == STATE_UNKNOWN
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_select_errors(hass: HomeAssistant, teslemetry: FakeTeslemetry) -> None:
    """A select raises the same errors as the other entities."""
    await setup_integration(hass)

    async def select() -> None:
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: CLIMATE_KEEPER, ATTR_OPTION: "camp"},
            blocking=True,
        )

    command = teslemetry.bluetooth.set_climate_keeper_mode
    command.side_effect = BluetoothTimeout()
    with pytest.raises(HomeAssistantError) as exc:
        await select()
    assert exc.value.translation_key == "bluetooth_failed"

    command.side_effect = None
    command.return_value = {"response": {"result": False, "reason": "busy"}}
    with pytest.raises(HomeAssistantError) as exc:
        await select()
    assert exc.value.translation_key == "command_failed"
    assert command.await_count == 2

    teslemetry.in_range = False
    with pytest.raises(HomeAssistantError) as exc:
        await select()
    assert exc.value.translation_key == "not_in_range"
    assert command.await_count == 2
    assert hass.states.get(CLIMATE_KEEPER).state == STATE_UNAVAILABLE
    teslemetry.assert_cloud_unused()


@pytest.mark.parametrize(("poll", "firmware"), POLLED_CLIMATE)
@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_target_temperature_polling(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, poll: bool, firmware: str
) -> None:
    """A polled car's temperature range follows Teslemetry's coordinator data."""
    teslemetry.poll = poll
    teslemetry.firmware = firmware
    teslemetry.coordinator.data = {
        "climate_state_min_avail_temp": 16,
        "climate_state_max_avail_temp": 27,
    }
    await setup_integration(hass)

    assert _limits(hass, TARGET_TEMPERATURE) == (16, 27)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: TARGET_TEMPERATURE, ATTR_VALUE: 15},
            blocking=True,
        )
    teslemetry.bluetooth.set_temps.assert_not_awaited()

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: TARGET_TEMPERATURE, ATTR_VALUE: 20.5},
        blocking=True,
    )
    teslemetry.bluetooth.set_temps.assert_awaited_once_with(
        driver_temp=20.5, passenger_temp=20.5
    )

    # Unknown again: back to the fixed range.
    teslemetry.coordinator.async_set_updated_data({})
    assert _limits(hass, TARGET_TEMPERATURE) == (15, 28)
    # A maximum below the minimum is not a usable range.
    teslemetry.coordinator.async_set_updated_data(
        {"climate_state_min_avail_temp": 20, "climate_state_max_avail_temp": 18}
    )
    assert _limits(hass, TARGET_TEMPERATURE) == (20, 28)
    teslemetry.coordinator.async_set_updated_data(
        {"climate_state_min_avail_temp": 30, "climate_state_max_avail_temp": 18}
    )
    assert _limits(hass, TARGET_TEMPERATURE) == (15, 28)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_target_temperature_streaming(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """A streaming car has the fixed temperature range."""
    teslemetry.coordinator.data = {
        "climate_state_min_avail_temp": 16,
        "climate_state_max_avail_temp": 27,
    }
    await setup_integration(hass)

    assert _limits(hass, TARGET_TEMPERATURE) == (15, 28)
    teslemetry.coordinator.async_set_updated_data(
        {"climate_state_min_avail_temp": 17, "climate_state_max_avail_temp": 26}
    )
    assert _limits(hass, TARGET_TEMPERATURE) == (15, 28)
    teslemetry.assert_cloud_unused()

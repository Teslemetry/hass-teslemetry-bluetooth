"""Tests for the Teslemetry Bluetooth Commands charge on solar binary sensor."""

from bleak.exc import BleakError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.teslemetry_bluetooth.const import (
    CHARGE_ON_SOLAR_INTERVAL,
    RANGE_CHECK_INTERVAL,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import (
    FakeTeslemetry,
    charge_on_solar_result,
    setup_integration,
    sleep_status,
)

CHARGE_ON_SOLAR = "binary_sensor.test_car_charge_on_solar_bluetooth"


@pytest.fixture(autouse=True)
def charge_on_solar_switch(teslemetry: FakeTeslemetry) -> None:
    """Give the vehicle Teslemetry's charge on solar switch."""
    teslemetry.entities = (*teslemetry.entities, ("switch", "charge_on_solar"))


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, interval: object
) -> None:
    freezer.tick(interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_read_while_awake(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, teslemetry: FakeTeslemetry
) -> None:
    """The state is read over Bluetooth at setup and on the interval."""
    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=False)
    teslemetry.bluetooth.get_charge_on_solar.return_value = charge_on_solar_result(
        enabled=True
    )
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_ON
    teslemetry.bluetooth.get_charge_on_solar.assert_awaited_once()

    teslemetry.bluetooth.get_charge_on_solar.return_value = charge_on_solar_result(
        enabled=False
    )
    await _tick(hass, freezer, CHARGE_ON_SOLAR_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF
    assert teslemetry.bluetooth.get_charge_on_solar.await_count == 2
    teslemetry.bluetooth.wake_up.assert_not_awaited()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_asleep_not_read(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, teslemetry: FakeTeslemetry
) -> None:
    """An asleep car is never read or woken, and the last value is kept."""
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_UNKNOWN

    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=False)
    await _tick(hass, freezer, CHARGE_ON_SOLAR_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF

    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=True)
    await _tick(hass, freezer, CHARGE_ON_SOLAR_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF
    teslemetry.bluetooth.get_charge_on_solar.assert_awaited_once()
    teslemetry.bluetooth.wake_up.assert_not_awaited()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_read_when_back_in_range(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, teslemetry: FakeTeslemetry
) -> None:
    """Out of range nothing is sent; the car is read when it comes back."""
    teslemetry.in_range = False
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_UNAVAILABLE
    teslemetry.bluetooth.vehicle_state.assert_not_awaited()

    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=False)
    teslemetry.in_range = True
    await _tick(hass, freezer, RANGE_CHECK_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF
    teslemetry.bluetooth.get_charge_on_solar.assert_awaited_once()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
@pytest.mark.parametrize(
    "result",
    [
        pytest.param(BleakError("disconnected"), id="error"),
        pytest.param({"response": {"result": False, "reason": "busy"}}, id="refused"),
    ],
)
async def test_failed_read_keeps_value(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    teslemetry: FakeTeslemetry,
    result: object,
) -> None:
    """A failed read keeps the last value."""
    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=False)
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF

    if isinstance(result, Exception):
        teslemetry.bluetooth.get_charge_on_solar.side_effect = result
    else:
        teslemetry.bluetooth.get_charge_on_solar.return_value = result
    await _tick(hass, freezer, CHARGE_ON_SOLAR_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_vehicle_state_error_not_read(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    teslemetry: FakeTeslemetry,
) -> None:
    """A VCSEC error instead of a status sends no read and keeps the last value."""
    teslemetry.bluetooth.vehicle_state.return_value = sleep_status(asleep=False)
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF

    teslemetry.bluetooth.vehicle_state.return_value = {
        "result": False,
        "reason": "GENERICERROR_UNKNOWN",
    }
    await _tick(hass, freezer, CHARGE_ON_SOLAR_INTERVAL)
    assert hass.states.get(CHARGE_ON_SOLAR).state == STATE_OFF
    assert "Update for" not in caplog.text
    teslemetry.bluetooth.get_charge_on_solar.assert_awaited_once()
    teslemetry.bluetooth.wake_up.assert_not_awaited()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_disabled_by_default(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, teslemetry: FakeTeslemetry
) -> None:
    """The binary sensor is disabled by default and then sends nothing."""
    await setup_integration(hass)
    entry = entity_registry.async_get(CHARGE_ON_SOLAR)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    teslemetry.bluetooth.vehicle_state.assert_not_awaited()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_follows_teslemetry_switch(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """Without Teslemetry's charge on solar switch, there is no binary sensor."""
    teslemetry.entities = tuple(
        entity for entity in teslemetry.entities if entity[0] != "switch"
    )
    await setup_integration(hass)
    assert hass.states.get(CHARGE_ON_SOLAR) is None
    teslemetry.bluetooth.vehicle_state.assert_not_awaited()

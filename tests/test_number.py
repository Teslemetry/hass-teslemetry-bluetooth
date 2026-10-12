"""Tests for the Teslemetry Bluetooth Commands numbers."""

import pytest

from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import FakeTeslemetry, setup_integration

CHARGE_LIMIT = "number.test_car_charge_limit_bluetooth"
CHARGING_AMPS = "number.test_car_charging_amps_bluetooth"


def _limits(hass: HomeAssistant, entity_id: str) -> tuple[float, float]:
    """Return the min and max of a number."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state.attributes[ATTR_MIN], state.attributes[ATTR_MAX]


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_streaming_max(hass: HomeAssistant, teslemetry: FakeTeslemetry) -> None:
    """A streaming car's charging amps maximum follows ChargeCurrentRequestMax."""
    await setup_integration(hass)

    # Unknown until the stream sends it.
    assert _limits(hass, CHARGING_AMPS) == (0, 48)
    assert _limits(hass, CHARGE_LIMIT) == (50, 100)

    teslemetry.stream_vehicle.send_current_request_max(32)
    assert _limits(hass, CHARGING_AMPS) == (0, 32)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: CHARGING_AMPS, ATTR_VALUE: 40},
            blocking=True,
        )
    teslemetry.bluetooth.set_charging_amps.assert_not_awaited()

    teslemetry.stream_vehicle.send_current_request_max(None)
    assert _limits(hass, CHARGING_AMPS) == (0, 48)
    # The stream has no charge limit maximum, so Teslemetry's coordinator is unused.
    teslemetry.coordinator.async_set_updated_data(
        {"charge_state_charge_limit_soc_max": 90}
    )
    assert _limits(hass, CHARGE_LIMIT) == (50, 100)
    teslemetry.assert_cloud_unused()


@pytest.mark.parametrize(
    ("poll", "firmware"),
    [
        pytest.param(True, "2026.20.1", id="polling"),
        pytest.param(False, "2024.20.9", id="old_firmware"),
    ],
)
@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_polling_max(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, poll: bool, firmware: str
) -> None:
    """A polled car's maximums follow Teslemetry's vehicle coordinator data."""
    teslemetry.poll = poll
    teslemetry.firmware = firmware
    teslemetry.coordinator.data = {
        "charge_state_charge_current_request_max": 40,
        "charge_state_charge_limit_soc_max": 90,
    }
    await setup_integration(hass)

    assert _limits(hass, CHARGING_AMPS) == (0, 40)
    assert _limits(hass, CHARGE_LIMIT) == (50, 90)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: CHARGE_LIMIT, ATTR_VALUE: 95},
            blocking=True,
        )
    teslemetry.bluetooth.set_charge_limit.assert_not_awaited()

    teslemetry.coordinator.async_set_updated_data(
        {"charge_state_charge_current_request_max": 24}
    )
    assert _limits(hass, CHARGING_AMPS) == (0, 24)
    # Unknown again: back to the fixed maximum.
    assert _limits(hass, CHARGE_LIMIT) == (50, 100)

    # The stream does not drive a polled car.
    teslemetry.stream_vehicle.send_current_request_max(16)
    assert _limits(hass, CHARGING_AMPS) == (0, 24)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_listeners_removed_on_unload(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """Unloading removes the maximum listeners from Teslemetry's data."""
    teslemetry.poll = True
    await setup_integration(hass)
    assert len(teslemetry.coordinator.listeners) == 2

    (entry,) = hass.config_entries.async_entries("teslemetry_bluetooth")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert teslemetry.coordinator.listeners == []

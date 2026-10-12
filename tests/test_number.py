"""Tests for the Teslemetry Bluetooth Commands numbers."""

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.teslemetry_bluetooth.const import DOMAIN
from homeassistant.components.number import (
    ATTR_MAX,
    ATTR_MIN,
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import VIN, FakeTeslemetry, setup_integration

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
    # A passive listener: it never opens or holds the stream by itself.
    assert [internal for _, _, internal in teslemetry.stream.listeners] == [True]

    teslemetry.stream.send({"ChargeCurrentRequestMax": 32})
    assert _limits(hass, CHARGING_AMPS) == (0, 32)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: CHARGING_AMPS, ATTR_VALUE: 40},
            blocking=True,
        )
    teslemetry.bluetooth.set_charging_amps.assert_not_awaited()

    # Some vehicles stream integers as strings.
    teslemetry.stream.send({"ChargeCurrentRequestMax": "40"})
    assert _limits(hass, CHARGING_AMPS) == (0, 40)

    teslemetry.stream.send({"ChargeCurrentRequestMax": None})
    assert _limits(hass, CHARGING_AMPS) == (0, 48)
    teslemetry.stream.send({"ChargeCurrentRequestMax": 32})
    teslemetry.stream.send({"ChargeCurrentRequestMax": "bad"})
    assert _limits(hass, CHARGING_AMPS) == (0, 48)
    # A maximum below the minimum is not a usable range.
    teslemetry.stream.send({"ChargeCurrentRequestMax": 32})
    teslemetry.stream.send({"ChargeCurrentRequestMax": -1})
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

    # A maximum below the minimum is not a usable range.
    teslemetry.coordinator.async_set_updated_data(
        {
            "charge_state_charge_current_request_max": 24,
            "charge_state_charge_limit_soc_max": 0,
        }
    )
    assert _limits(hass, CHARGE_LIMIT) == (50, 100)

    # The stream does not drive a polled car.
    teslemetry.stream.send({"ChargeCurrentRequestMax": 16})
    assert _limits(hass, CHARGING_AMPS) == (0, 24)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry")
async def test_streaming_max_restored(
    hass: HomeAssistant, config_entry: MockConfigEntry, teslemetry: FakeTeslemetry
) -> None:
    """A streaming car keeps its last maximum over a restart."""
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(CHARGING_AMPS, STATE_UNKNOWN),
                {
                    "native_max_value": 32,
                    "native_min_value": 0,
                    "native_step": 1,
                    "native_unit_of_measurement": "A",
                    "native_value": None,
                },
            )
        ],
    )
    # The entity id must be registered for the restored state to apply.
    er.async_get(hass).async_get_or_create(
        NUMBER_DOMAIN,
        DOMAIN,
        f"{VIN}-bluetooth-set_charging_amps",
        suggested_object_id="test_car_charging_amps_bluetooth",
    )
    await setup_integration(hass)

    assert _limits(hass, CHARGING_AMPS) == (0, 32)
    teslemetry.stream.send({"ChargeCurrentRequestMax": 24})
    assert _limits(hass, CHARGING_AMPS) == (0, 24)


@pytest.mark.parametrize("poll", [True, False], ids=["polling", "streaming"])
@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_listeners_removed_on_unload(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, poll: bool
) -> None:
    """Unloading removes the maximum listeners from Teslemetry's data."""
    teslemetry.poll = poll
    await setup_integration(hass)
    assert len(teslemetry.coordinator.listeners) + len(teslemetry.stream.listeners) == (
        2 if poll else 1
    )

    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert teslemetry.coordinator.listeners == []
    assert teslemetry.stream.listeners == []

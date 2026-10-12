"""Tests for the Teslemetry Bluetooth Commands config flow."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.teslemetry_bluetooth.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ADDRESS, VIN

pytestmark = pytest.mark.usefixtures("teslemetry")


async def test_flow(hass: HomeAssistant) -> None:
    """The flow creates one entry once a vehicle is paired over Bluetooth."""
    MockConfigEntry(
        domain="teslemetry",
        subentries_data=[
            ConfigSubentryData(
                data={"vin": VIN, "address": ADDRESS},
                subentry_type="vehicle",
                title="Test Car",
                unique_id=VIN,
            )
        ],
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Teslemetry Bluetooth Commands"
    assert result["data"] == {}


async def test_flow_no_bluetooth_vehicles(hass: HomeAssistant) -> None:
    """The flow aborts when no Teslemetry vehicle is paired over Bluetooth."""
    MockConfigEntry(domain="teslemetry").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_bluetooth_vehicles"


async def test_flow_single_instance(hass: HomeAssistant) -> None:
    """Only one entry can exist."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

"""Fixtures for Teslemetry Bluetooth Commands tests."""

from collections.abc import Callable, Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)
from tesla_fleet_api.router import VehicleRouter

from custom_components.teslemetry_bluetooth.const import (
    COMMANDS,
    DOMAIN,
    ENTITY_COMMANDS,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.setup import async_setup_component

VIN = "LRWYGCEK1PC000001"
ADDRESS = "AA:BB:CC:DD:EE:FF"
SUCCESS = {"response": {"result": True, "reason": ""}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Enable custom integrations."""
    yield


class FakeCoordinator:
    """A stand-in for Teslemetry's vehicle data coordinator."""

    def __init__(self) -> None:
        """Initialize with no vehicle data."""
        self.data: dict[str, Any] = {}
        self.listeners: list[Callable[[], None]] = []

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Add a listener."""
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def async_set_updated_data(self, data: dict[str, Any]) -> None:
        """Replace the data and notify listeners."""
        self.data = data
        for listener in list(self.listeners):
            listener()


class FakeStream:
    """A stand-in for Teslemetry's TeslemetryStream."""

    def __init__(self) -> None:
        """Initialize with no listeners."""
        self.listeners: list[
            tuple[Callable[[dict[str, Any]], None], dict[str, Any], bool]
        ] = []

    def async_add_listener(
        self,
        callback: Callable[[dict[str, Any]], None],
        filters: dict[str, Any],
        internal: bool = False,
    ) -> Callable[[], None]:
        """Add a listener."""
        listener = (callback, filters, internal)
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def send(self, data: dict[str, Any]) -> None:
        """Stream vehicle data to each listener whose filter matches."""
        for callback, filters, _ in list(self.listeners):
            if filters["vin"] == VIN and filters["data"].keys() <= data.keys():
                callback({"vin": VIN, "data": data})


class FakeTeslemetry:
    """A Teslemetry stand-in whose runtime data matches core 2026.10.0."""

    def __init__(self) -> None:
        """Initialize the backends."""
        self.in_range = True
        self.create_device = True
        self.bluetooth = self.make_backend("bluetooth")
        # Any call on the cloud backend is recorded in cloud.mock_calls.
        self.cloud = self.make_backend("cloud")
        self.runtime_data: SimpleNamespace | None = None
        # Teslemetry streams this vehicle unless poll is set or firmware is old.
        self.poll = False
        self.firmware = "2026.20.1"
        self.coordinator = FakeCoordinator()
        self.stream = FakeStream()
        # Only the stream is set: the vehicle's listen_* helpers call the cloud.
        self.stream_vehicle = SimpleNamespace(stream=self.stream)

    @staticmethod
    def make_backend(name: str) -> MagicMock:
        """Return a vehicle backend whose commands all succeed."""
        backend = MagicMock(name=name)
        for command in (*COMMANDS, *ENTITY_COMMANDS):
            setattr(backend, command, AsyncMock(return_value=SUCCESS))
        return backend

    def build_runtime_data(self) -> SimpleNamespace:
        """Build runtime data shaped like Teslemetry's TeslemetryData."""
        router = VehicleRouter(self.bluetooth, self.cloud, health=lambda: self.in_range)
        vehicle = SimpleNamespace(
            api=router,
            vin=VIN,
            poll=self.poll,
            firmware=self.firmware,
            coordinator=self.coordinator,
            stream_vehicle=self.stream_vehicle,
            device=DeviceInfo(identifiers={("teslemetry", VIN)}, name="Test Car"),
        )
        return SimpleNamespace(vehicles=[vehicle])

    def assert_cloud_unused(self) -> None:
        """Assert no cloud method was ever called."""
        assert self.cloud.mock_calls == []


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable entities that are disabled by default."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def teslemetry(hass: HomeAssistant) -> Generator[FakeTeslemetry]:
    """Replace the Teslemetry integration with a stand-in."""
    fake = FakeTeslemetry()

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        entry.runtime_data = (
            fake.runtime_data
            if fake.runtime_data is not None
            else fake.build_runtime_data()
        )
        if fake.create_device:
            dr.async_get(hass).async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={("teslemetry", VIN)},
                name="Test Car",
            )
        return True

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        return True

    mock_integration(
        hass,
        MockModule(
            "teslemetry",
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )
    mock_platform(hass, "teslemetry.config_flow")
    with mock_config_flow("teslemetry", ConfigFlow):
        yield fake


@pytest.fixture
def teslemetry_entry(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> MockConfigEntry:
    """Add a Teslemetry entry."""
    entry = MockConfigEntry(
        domain="teslemetry",
        subentries_data=[
            ConfigSubentryData(
                data={"vin": VIN, "address": ADDRESS},
                subentry_type="vehicle",
                title="Test Car",
                unique_id=VIN,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a Teslemetry Bluetooth Commands entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Teslemetry Bluetooth Commands")
    entry.add_to_hass(hass)
    return entry


async def setup_integration(hass: HomeAssistant) -> None:
    """Set up Teslemetry and this integration."""
    assert await async_setup_component(hass, "teslemetry", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

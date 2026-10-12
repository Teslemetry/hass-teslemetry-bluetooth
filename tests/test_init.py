"""Tests for Teslemetry Bluetooth Commands."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from bleak.exc import BleakError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from tesla_fleet_api.exceptions import (
    BluetoothCommandFailed,
    BluetoothTimeout,
    BluetoothTransportError,
    BluetoothUnconfirmedCommand,
)
from tesla_fleet_api.router import VehicleRouter

from custom_components.teslemetry_bluetooth.const import (
    DOMAIN,
    ISSUE_INCOMPATIBLE_TESLEMETRY,
    RANGE_CHECK_INTERVAL,
)
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from .conftest import VIN, FakeTeslemetry, setup_integration

START_CHARGING = "button.test_car_start_charging_bluetooth"
STOP_CHARGING = "button.test_car_stop_charging_bluetooth"
LOCK = "button.test_car_lock_bluetooth"
UNLOCK = "button.test_car_unlock_bluetooth"
CHARGE_LIMIT = "number.test_car_charge_limit_bluetooth"
CHARGING_AMPS = "number.test_car_charging_amps_bluetooth"

# (entity, platform service, service data, Bluetooth command, command kwargs)
ENTITY_COMMANDS = [
    (START_CHARGING, BUTTON_DOMAIN, SERVICE_PRESS, {}, "charge_start", {}),
    (STOP_CHARGING, BUTTON_DOMAIN, SERVICE_PRESS, {}, "charge_stop", {}),
    (LOCK, BUTTON_DOMAIN, SERVICE_PRESS, {}, "door_lock", {}),
    (UNLOCK, BUTTON_DOMAIN, SERVICE_PRESS, {}, "door_unlock", {}),
    (
        CHARGE_LIMIT,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_VALUE: 80},
        "set_charge_limit",
        {"percent": 80},
    ),
    (
        CHARGING_AMPS,
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_VALUE: 16},
        "set_charging_amps",
        {"charging_amps": 16},
    ),
]

FAILURES = [
    pytest.param(BluetoothTransportError(), id="busy_or_no_slot"),
    pytest.param(BluetoothTimeout(), id="timeout"),
    pytest.param(BluetoothUnconfirmedCommand(), id="unconfirmed"),
    pytest.param(BluetoothCommandFailed(), id="failed"),
    pytest.param(TimeoutError(), id="asyncio_timeout"),
    pytest.param(BleakError("disconnected"), id="bleak_error"),
    pytest.param(ValueError("Session shared key is missing"), id="no_session"),
]


def _device_id(hass: HomeAssistant) -> str:
    """Return the id of Teslemetry's device for the test car."""
    (teslemetry_entry,) = hass.config_entries.async_entries("teslemetry")
    device = dr.async_get(hass).async_get_device_by_identifier(
        ("teslemetry", VIN), teslemetry_entry.entry_id
    )
    assert device is not None
    return device.id


@pytest.mark.usefixtures("teslemetry_entry")
async def test_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
) -> None:
    """Charging entities are enabled, lock entities are disabled, all on the car."""
    await setup_integration(hass)

    device_id = _device_id(hass)
    for entity_id, enabled in (
        (START_CHARGING, True),
        (STOP_CHARGING, True),
        (CHARGE_LIMIT, True),
        (CHARGING_AMPS, True),
        (LOCK, False),
        (UNLOCK, False),
    ):
        entry = entity_registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.device_id == device_id
        assert (entry.disabled_by is None) is enabled
    assert hass.states.get(CHARGE_LIMIT).state == "unknown"
    # No second device: the entities sit on Teslemetry's own device.
    assert (
        dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        == []
    )
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
@pytest.mark.parametrize(
    ("entity_id", "domain", "service", "data", "command", "kwargs"), ENTITY_COMMANDS
)
async def test_entity_command_in_range(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    entity_id: str,
    domain: str,
    service: str,
    data: dict[str, int],
    command: str,
    kwargs: dict[str, int],
) -> None:
    """In range, each entity sends its command over Bluetooth only."""
    await setup_integration(hass)

    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )
    getattr(teslemetry.bluetooth, command).assert_awaited_once_with(**kwargs)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures(
    "teslemetry_entry", "config_entry", "entity_registry_enabled_by_default"
)
async def test_out_of_range(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    teslemetry: FakeTeslemetry,
) -> None:
    """Out of range, entities go unavailable and commands fail without the cloud."""
    await setup_integration(hass)
    assert hass.states.get(START_CHARGING).state != STATE_UNAVAILABLE

    # The car leaves range before the next check: the press fails.
    teslemetry.in_range = False
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: START_CHARGING},
            blocking=True,
        )
    assert exc.value.translation_key == "not_in_range"
    assert "not reached over Bluetooth" in str(exc.value)
    for entity_id, *_ in ENTITY_COMMANDS:
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    # The action fails the same way.
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_DEVICE_ID: _device_id(hass), "command": "door_unlock"},
            blocking=True,
        )
    assert exc.value.translation_key == "not_in_range"
    teslemetry.bluetooth.charge_start.assert_not_awaited()
    teslemetry.bluetooth.door_unlock.assert_not_awaited()
    teslemetry.assert_cloud_unused()

    # The periodic check brings the entities back when the car returns.
    teslemetry.in_range = True
    freezer.tick(RANGE_CHECK_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    for entity_id, *_ in ENTITY_COMMANDS:
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE

    # And the periodic check takes them away again.
    teslemetry.in_range = False
    freezer.tick(RANGE_CHECK_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(START_CHARGING).state == STATE_UNAVAILABLE
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_out_of_range_at_setup(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """A car out of range at startup has unavailable entities."""
    teslemetry.in_range = False
    await setup_integration(hass)

    assert hass.states.get(START_CHARGING).state == STATE_UNAVAILABLE
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
@pytest.mark.parametrize("error", FAILURES)
async def test_bluetooth_failure(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, error: BaseException
) -> None:
    """A Bluetooth failure raises an error and never reaches the cloud."""
    await setup_integration(hass)
    teslemetry.bluetooth.set_charge_limit.side_effect = error

    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: CHARGE_LIMIT, ATTR_VALUE: 70},
            blocking=True,
        )
    assert exc.value.translation_key == "bluetooth_failed"
    assert "not reached over Bluetooth" in str(exc.value)
    assert "not sent to the cloud" in str(exc.value)
    teslemetry.bluetooth.set_charge_limit.assert_awaited_once_with(percent=70)
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
@pytest.mark.parametrize("reason", ["already_set", "not_charging", "requested"])
async def test_command_already_done(
    hass: HomeAssistant, teslemetry: FakeTeslemetry, reason: str
) -> None:
    """A car already in the requested state is a success."""
    await setup_integration(hass)
    teslemetry.bluetooth.charge_stop.return_value = {
        "response": {"result": False, "reason": reason}
    }

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: STOP_CHARGING}, blocking=True
    )
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
@pytest.mark.parametrize(
    ("result", "translation_key"),
    [
        pytest.param(
            {"response": {"result": False, "reason": "cable_disconnected"}},
            "command_failed",
            id="reason",
        ),
        pytest.param({"response": {"result": False}}, "command_failed", id="no_reason"),
        pytest.param({}, "command_no_response", id="no_response"),
    ],
)
async def test_command_refused(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    result: dict[str, dict[str, bool | str]],
    translation_key: str,
) -> None:
    """A refused command raises an error and never reaches the cloud."""
    await setup_integration(hass)
    teslemetry.bluetooth.charge_stop.return_value = result

    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: STOP_CHARGING}, blocking=True
        )
    assert exc.value.translation_key == translation_key
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_send_command_action(
    hass: HomeAssistant, teslemetry: FakeTeslemetry
) -> None:
    """The action sends a command with arguments over Bluetooth only."""
    await setup_integration(hass)
    device_id = _device_id(hass)

    await hass.services.async_call(
        DOMAIN,
        "send_command",
        {
            ATTR_DEVICE_ID: device_id,
            "command": "set_charging_amps",
            "arguments": {"charging_amps": 12},
        },
        blocking=True,
    )
    teslemetry.bluetooth.set_charging_amps.assert_awaited_once_with(charging_amps=12)

    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_DEVICE_ID: device_id, "command": "set_charge_limit"},
            blocking=True,
        )
    assert exc.value.translation_key == "invalid_arguments"

    teslemetry.bluetooth.door_lock.side_effect = BluetoothTransportError()
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_DEVICE_ID: device_id, "command": "door_lock"},
            blocking=True,
        )
    assert exc.value.translation_key == "bluetooth_failed"
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_send_command_unpaired_device(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """The action refuses a device that is not a Bluetooth-paired vehicle."""
    await setup_integration(hass)
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}, name="Other"
    )

    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_DEVICE_ID: device.id, "command": "charge_start"},
            blocking=True,
        )
    assert exc.value.translation_key == "not_paired"

    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN,
            "send_command",
            {ATTR_DEVICE_ID: "missing", "command": "charge_start"},
            blocking=True,
        )
    assert exc.value.translation_key == "invalid_device"


@pytest.mark.usefixtures("teslemetry_entry")
@pytest.mark.parametrize(
    "runtime_data",
    [
        pytest.param(SimpleNamespace(), id="no_vehicles"),
        pytest.param(
            SimpleNamespace(vehicles=[SimpleNamespace(vin=VIN, device={})]),
            id="no_api",
        ),
    ],
)
async def test_incompatible_teslemetry(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    config_entry: MockConfigEntry,
    runtime_data: SimpleNamespace,
) -> None:
    """Missing Teslemetry internals raise a repair and load no entities."""
    teslemetry.runtime_data = runtime_data
    await setup_integration(hass)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)
    assert issue is not None
    assert issue.translation_placeholders["version"] == "Home Assistant 2026.10.0"
    assert (
        er.async_entries_for_config_entry(entity_registry, config_entry.entry_id) == []
    )
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry")
async def test_incompatible_bluetooth_backend(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    teslemetry: FakeTeslemetry,
    config_entry: MockConfigEntry,
) -> None:
    """A Bluetooth backend without a needed command raises the repair."""
    teslemetry.bluetooth = MagicMock(spec=["charge_start"])
    await setup_integration(hass)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)


@pytest.mark.usefixtures("teslemetry_entry")
async def test_incompatible_router(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    teslemetry: FakeTeslemetry,
    config_entry: MockConfigEntry,
) -> None:
    """A VehicleRouter without the in-range check raises the repair."""

    class OldRouter(VehicleRouter[MagicMock, MagicMock]):
        is_healthy = None  # type: ignore[assignment]

    teslemetry.runtime_data = SimpleNamespace(
        vehicles=[
            SimpleNamespace(
                api=OldRouter(teslemetry.bluetooth, teslemetry.cloud), vin=VIN
            )
        ]
    )
    await setup_integration(hass)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_vehicle_without_device(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
) -> None:
    """A vehicle Teslemetry has no device for gets no entities."""
    teslemetry.create_device = False
    await setup_integration(hass)

    assert entity_registry.async_get(START_CHARGING) is None
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("config_entry")
async def test_cloud_only_vehicle(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
) -> None:
    """A vehicle Teslemetry controls only through the cloud gets no entities."""
    teslemetry.runtime_data = SimpleNamespace(
        vehicles=[SimpleNamespace(api=teslemetry.cloud, vin=VIN, device={})]
    )
    await setup_integration(hass)

    assert entity_registry.async_get(START_CHARGING) is None
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("config_entry")
async def test_reload_follows_teslemetry(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
) -> None:
    """A Teslemetry reload rebuilds the entities on its new runtime data."""
    await setup_integration(hass)
    old_bluetooth = teslemetry.bluetooth

    teslemetry.bluetooth = teslemetry.make_backend("bluetooth2")
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: START_CHARGING}, blocking=True
    )
    teslemetry.bluetooth.charge_start.assert_awaited_once()
    old_bluetooth.charge_start.assert_not_awaited()
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry")
async def test_unload(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    config_entry: MockConfigEntry,
) -> None:
    """The entry unloads and its removal clears the repair."""
    await setup_integration(hass)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert await hass.config_entries.async_remove(config_entry.entry_id)
    assert not issue_registry.async_get_issue(DOMAIN, ISSUE_INCOMPATIBLE_TESLEMETRY)


@pytest.mark.usefixtures("teslemetry_entry", "config_entry")
async def test_vehicle_in_two_teslemetry_entries(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A car shared by two Teslemetry accounts gets one set of entities."""
    MockConfigEntry(domain="teslemetry").add_to_hass(hass)
    await setup_integration(hass)

    assert entity_registry.async_get(START_CHARGING) is not None
    assert entity_registry.async_get(f"{START_CHARGING}_2") is None


def _entity_ids(hass: HomeAssistant, config_entry: MockConfigEntry) -> set[str]:
    """Return the registered entity ids of this integration."""
    return {
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            er.async_get(hass), config_entry.entry_id
        )
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_unpaired_vehicle_entities_removed(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """A vehicle that loses its Bluetooth pairing loses its entities."""
    await setup_integration(hass)
    assert len(_entity_ids(hass, config_entry)) == len(ENTITY_COMMANDS)

    # Removing the Bluetooth subentry reloads Teslemetry with a cloud-only car.
    teslemetry.runtime_data = SimpleNamespace(
        vehicles=[SimpleNamespace(api=teslemetry.cloud, vin=VIN, device={})]
    )
    (subentry_id,) = teslemetry_entry.subentries
    assert hass.config_entries.async_remove_subentry(teslemetry_entry, subentry_id)
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity_ids(hass, config_entry) == set()
    assert hass.states.get(START_CHARGING) is None
    teslemetry.assert_cloud_unused()


async def test_bluetooth_key_not_loaded_keeps_entities(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """A paired car Teslemetry falls back to the cloud for keeps its entities."""
    await setup_integration(hass)
    entity_ids = _entity_ids(hass, config_entry)

    # Teslemetry could not load the Bluetooth key, so the car is cloud only.
    teslemetry.runtime_data = SimpleNamespace(
        vehicles=[SimpleNamespace(api=teslemetry.cloud, vin=VIN, device={})]
    )
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()
    assert _entity_ids(hass, config_entry) == entity_ids
    assert hass.states.get(START_CHARGING).state == STATE_UNAVAILABLE

    # The key loads again on the next reload.
    teslemetry.runtime_data = None
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(START_CHARGING).state != STATE_UNAVAILABLE
    teslemetry.assert_cloud_unused()


@pytest.mark.usefixtures("teslemetry_entry")
async def test_shared_vehicle_paired_in_other_entry_keeps_entities(
    hass: HomeAssistant,
    teslemetry: FakeTeslemetry,
    config_entry: MockConfigEntry,
) -> None:
    """A shared car keeps its entities while another account still pairs it."""
    MockConfigEntry(
        domain="teslemetry",
        subentries_data=[
            ConfigSubentryData(
                data={"vin": VIN},
                subentry_type="vehicle",
                title="Test Car",
                unique_id=VIN,
            )
        ],
    ).add_to_hass(hass)
    await setup_integration(hass)
    entity_ids = _entity_ids(hass, config_entry)

    entity = er.async_get(hass).async_get(START_CHARGING)
    assert entity is not None and entity.device_id is not None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    first = hass.config_entries.async_get_known_entry(device.config_entry_id)
    (second,) = (
        entry
        for entry in hass.config_entries.async_entries("teslemetry")
        if entry is not first
    )

    # The other account could not load its key, then the account that owns
    # the car's device loses the pairing.
    teslemetry.runtime_data = SimpleNamespace(
        vehicles=[SimpleNamespace(api=teslemetry.cloud, vin=VIN, device={})]
    )
    assert await hass.config_entries.async_reload(second.entry_id)
    (subentry_id,) = first.subentries
    assert hass.config_entries.async_remove_subentry(first, subentry_id)
    assert await hass.config_entries.async_reload(first.entry_id)
    await hass.async_block_till_done()

    assert _entity_ids(hass, config_entry) == entity_ids
    teslemetry.assert_cloud_unused()


async def test_vehicle_leaves_account(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """A vehicle Teslemetry no longer has leaves no orphaned entities."""
    await setup_integration(hass)

    # Teslemetry removes the device of a vehicle that left the account.
    teslemetry.runtime_data = SimpleNamespace(vehicles=[])
    teslemetry.create_device = False
    device_registry.async_remove_device(_device_id(hass))
    assert await hass.config_entries.async_reload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity_ids(hass, config_entry) == set()


async def test_teslemetry_entry_removed(
    hass: HomeAssistant,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Removing the Teslemetry entry removes the entities on its vehicles."""
    await setup_integration(hass)
    assert _entity_ids(hass, config_entry)

    assert await hass.config_entries.async_remove(teslemetry_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity_ids(hass, config_entry) == set()
    assert hass.states.get(START_CHARGING) is None


async def test_teslemetry_not_loaded_keeps_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    teslemetry: FakeTeslemetry,
    teslemetry_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Entities and their settings survive while Teslemetry is not loaded."""
    await setup_integration(hass)
    entity_registry.async_update_entity(START_CHARGING, name="Charge now")
    entity_ids = _entity_ids(hass, config_entry)

    assert await hass.config_entries.async_unload(teslemetry_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity_ids(hass, config_entry) == entity_ids
    assert hass.states.get(START_CHARGING).state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_setup(teslemetry_entry.entry_id)
    await hass.async_block_till_done()
    assert _entity_ids(hass, config_entry) == entity_ids
    assert entity_registry.async_get(START_CHARGING).name == "Charge now"
    assert hass.states.get(START_CHARGING).state != STATE_UNAVAILABLE
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: START_CHARGING}, blocking=True
    )
    teslemetry.bluetooth.charge_start.assert_awaited_once()
    teslemetry.assert_cloud_unused()

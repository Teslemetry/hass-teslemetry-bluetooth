"""Constants for the Teslemetry Bluetooth Commands integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "teslemetry_bluetooth"
TESLEMETRY_DOMAIN: Final = "teslemetry"

LOGGER = logging.getLogger(__package__)

# Teslemetry's Bluetooth pairing subentry type and its VIN key.
TESLEMETRY_SUBENTRY_TYPE_VEHICLE: Final = "vehicle"
TESLEMETRY_CONF_VIN: Final = "vin"

# The oldest Teslemetry that exposes the Bluetooth runtime this integration reuses.
MIN_TESLEMETRY_VERSION: Final = "Home Assistant 2026.10.0"
ISSUE_INCOMPATIBLE_TESLEMETRY: Final = "incompatible_teslemetry"

# How often Teslemetry's own in-range check is re-read to update availability.
RANGE_CHECK_INTERVAL: Final = timedelta(seconds=10)

CHARGE_LIMIT_MIN: Final = 50
CHARGE_LIMIT_MAX: Final = 100
CHARGING_AMPS_MIN: Final = 0
CHARGING_AMPS_MAX: Final = 48
# Tesla's media volume has 31 steps of 1/3, up to 10.333.
VOLUME_MAX: Final = 31 / 3
VOLUME_STEP: Final = 1 / 3

# Every command this integration sends.
COMMANDS: Final = (
    "wake_up",
    "charge_start",
    "charge_stop",
    "door_lock",
    "door_unlock",
    "set_charge_limit",
    "set_charging_amps",
    "media_toggle_playback",
    "media_next_track",
    "media_prev_track",
    "adjust_volume",
    "set_sentry_mode",
    "set_valet_mode",
    "remote_auto_seat_climate_request",
    "remote_auto_steering_wheel_heat_climate_request",
    "set_preconditioning_max",
    "guest_mode",
    "flash_lights",
    "honk_horn",
    "remote_boombox",
    "trigger_homelink",
    "remote_start_drive",
    "schedule_software_update",
)

# Vehicle command results that mean the car is already in the requested state.
ACCEPTED_REASONS: Final = ("already_set", "not_charging", "requested")

"""Constants for the Teslemetry Bluetooth Commands integration."""

from datetime import timedelta
import logging
from typing import Any, Final

import probatio

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

# Every command this integration sends, with the schema of its arguments.
COMMANDS: Final[dict[str, dict[Any, Any]]] = {
    "charge_start": {},
    "charge_stop": {},
    "door_lock": {},
    "door_unlock": {},
    "set_charge_limit": {
        probatio.Required("percent"): probatio.All(
            probatio.Coerce(int), probatio.Range(CHARGE_LIMIT_MIN, CHARGE_LIMIT_MAX)
        )
    },
    "set_charging_amps": {
        probatio.Required("charging_amps"): probatio.All(
            probatio.Coerce(int), probatio.Range(CHARGING_AMPS_MIN, CHARGING_AMPS_MAX)
        )
    },
}

# Vehicle command results that mean the car is already in the requested state.
ACCEPTED_REASONS: Final = ("already_set", "not_charging", "requested")

"""Config flow for Teslemetry Bluetooth Commands."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, TESLEMETRY_DOMAIN, TESLEMETRY_SUBENTRY_TYPE_VEHICLE


class TeslemetryBluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one entry that covers every Teslemetry account."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup once a Teslemetry vehicle is paired over Bluetooth."""
        if not any(
            subentry.subentry_type == TESLEMETRY_SUBENTRY_TYPE_VEHICLE
            for teslemetry_entry in self.hass.config_entries.async_entries(
                TESLEMETRY_DOMAIN
            )
            for subentry in teslemetry_entry.subentries.values()
        ):
            return self.async_abort(reason="no_bluetooth_vehicles")
        if user_input is not None:
            return self.async_create_entry(
                title="Teslemetry Bluetooth Commands", data={}
            )
        return self.async_show_form(step_id="user")

"""Actions for Teslemetry Bluetooth Commands."""

import probatio

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import COMMANDS, DOMAIN
from .vehicle import TeslemetryBluetoothVehicle

SERVICE_SEND_COMMAND = "send_command"
ATTR_COMMAND = "command"
ATTR_ARGUMENTS = "arguments"

SEND_COMMAND_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_DEVICE_ID): cv.string,
        probatio.Required(ATTR_COMMAND): probatio.In(list(COMMANDS)),
        probatio.Optional(ATTR_ARGUMENTS, default={}): dict,
    }
)


def _async_get_vehicle(
    hass: HomeAssistant, device_id: str
) -> TeslemetryBluetoothVehicle:
    """Return the Bluetooth vehicle for a Teslemetry vehicle device."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_device"
        )
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        runtime_data: dict[str, TeslemetryBluetoothVehicle] = entry.runtime_data
        for vehicle in runtime_data.values():
            if vehicle.device.id == device_id:
                return vehicle
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="not_paired",
        translation_placeholders={"device": device.name_by_user or device.name or ""},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""

    async def _async_send_command(call: ServiceCall) -> None:
        vehicle = _async_get_vehicle(hass, call.data[ATTR_DEVICE_ID])
        command: str = call.data[ATTR_COMMAND]
        try:
            arguments = probatio.Schema(COMMANDS[command])(call.data[ATTR_ARGUMENTS])
        except probatio.Invalid as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_arguments",
                translation_placeholders={"command": command, "error": str(err)},
            ) from err
        await vehicle.async_send(command, **arguments)

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_COMMAND, _async_send_command, schema=SEND_COMMAND_SCHEMA
    )

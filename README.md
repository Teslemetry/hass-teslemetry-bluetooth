# Teslemetry Bluetooth Commands

Bluetooth-only command entities for Tesla vehicles in the [Teslemetry](https://www.home-assistant.io/integrations/teslemetry) integration for Home Assistant.

Teslemetry sends each command to a Bluetooth-paired vehicle over Bluetooth first and, if that fails, over the cloud. This companion adds separate entities that **only** use Bluetooth. If the car is not reached over Bluetooth, the command fails with an error. It is never sent to the cloud.

Your existing Teslemetry entities do not change.

## Requirements

- Home Assistant 2026.10.0 or later.
- The Teslemetry integration, set up, with at least one vehicle paired over Bluetooth (in Teslemetry, add a **Bluetooth vehicle**).

This integration does not pair a vehicle, create a key or open a Bluetooth connection of its own. It reuses Teslemetry's key, pairing and Bluetooth connection.

The Teslemetry integration must be loaded. If Teslemetry cannot start (for example, the Teslemetry cloud is not reachable when Home Assistant starts), this integration adds no entities until Teslemetry loads.

## Installation

1. Add this repository to HACS as a custom repository (category: Integration), or copy `custom_components/teslemetry_bluetooth` into your `config/custom_components` folder.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and add **Teslemetry Bluetooth Commands**.

One entry covers every Teslemetry account and every vehicle that is paired over Bluetooth.

## Entities

The entities are added to each Bluetooth-paired vehicle's existing Teslemetry device.

| Entity | Type | Enabled by default |
| --- | --- | --- |
| Wake (Bluetooth) | Button | Yes |
| Start charging (Bluetooth) | Button | Yes |
| Stop charging (Bluetooth) | Button | Yes |
| Charge limit (Bluetooth) | Number (50-100 %) | Yes |
| Charging amps (Bluetooth) | Number (0 A to the car's maximum) | Yes |
| Lock (Bluetooth) | Button | No |
| Unlock (Bluetooth) | Button | No |
| Play/pause (Bluetooth) | Button | No |
| Next track (Bluetooth) | Button | No |
| Previous track (Bluetooth) | Button | No |
| Volume (Bluetooth) | Number (0-10.33, in steps of 1/3) | No |
| Sentry mode on (Bluetooth) | Button | No |
| Sentry mode off (Bluetooth) | Button | No |
| Valet mode on (Bluetooth) | Button | No |
| Valet mode off (Bluetooth) | Button | No |
| Auto seat climate left on (Bluetooth) | Button | No |
| Auto seat climate left off (Bluetooth) | Button | No |
| Auto seat climate right on (Bluetooth) | Button | No |
| Auto seat climate right off (Bluetooth) | Button | No |
| Auto steering wheel heater on (Bluetooth) | Button | No |
| Auto steering wheel heater off (Bluetooth) | Button | No |
| Defrost on (Bluetooth) | Button | No |
| Defrost off (Bluetooth) | Button | No |
| Guest mode on (Bluetooth) | Button | No |
| Guest mode off (Bluetooth) | Button | No |

- The entities are available only while the vehicle is in Bluetooth range, as reported by Teslemetry. Range is checked every 10 seconds and before each command.
- The entities only send commands. They show no vehicle state: the current charge limit, charging state, lock state and switch states stay on the Teslemetry entities. The numbers always show `unknown`.
- Charging amps and Charge limit use the car's own maximum from Teslemetry's data, the same value Teslemetry's own numbers use. While Teslemetry has no value, the maximum is 48 A and 100 %. This integration never asks the cloud for the value, so a streaming car sends it only while Teslemetry's own Charging amps entity is enabled.
- Wake sends only the Bluetooth wake signal. The car can take a few more seconds to answer other commands after it wakes. The button never wakes the car through the cloud.
- Lock and Unlock are buttons, not a lock entity, so voice assistants do not ask for a confirmation or code. They are disabled by default; enable them only if you accept that.
- Play/pause toggles playback: it plays if the car is paused and pauses if the car is playing. Volume uses the car's own scale from 0 to 10.33, the same scale Teslemetry uses: Teslemetry's media player volume of 100 % is 10.33. The current playback and volume stay on Teslemetry's media player.
- Each of Teslemetry's command switches (Sentry mode, Valet mode, Auto seat climate left and right, Auto steering wheel heater, Defrost and Guest mode) has an On and an Off button, because a switch would need the car's state. The buttons are disabled by default. Valet mode on sends an empty PIN, as Teslemetry's switch does. Guest mode buttons are added only to vehicles that Teslemetry streams, as Teslemetry's own Guest mode switch is.

## Errors

- **Not in Bluetooth range:** the car is not reached over Bluetooth, and the command is not sent.
- **Bluetooth failure** (the car is busy, no Bluetooth proxy slot is free, a timeout): the command fails, and it is not sent to the cloud. The command can have reached the car before the failure, so check the car's state in Teslemetry before you try again.
- **Command refused:** the car was reached and refused the command, for example because no cable is connected.

## Compatibility

This integration reads Teslemetry's runtime objects. If the installed Teslemetry does not provide them, it creates a repair issue that names the Teslemetry version it needs, and it adds no entities.

## License

Apache-2.0

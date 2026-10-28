# DEVIreg Smart for Home Assistant

Custom integration for Danfoss DEVIreg Smart Wi-Fi floor heating thermostats.

> **Status:** early but working. Runs daily against a real DEVIreg Smart
> (firmware 1.0.127): pairing, live push updates, mode and setpoint control.
> The protocol is a Python port of [OpenSDG](https://github.com/Sonic-Amiga/opensdg),
> with tests against a simulated Danfoss server. Danfoss Icon is not supported.

## How it works

DEVIreg Smart has no local API. The thermostats and the DEVIsmart app talk
through Danfoss's SecureDeviceGrid cloud relay. This integration joins your
house the same way another phone would: you generate a one-time code in the
app, Home Assistant pairs with the app, receives the list of thermostats, and
then connects to each one. Updates are pushed by the thermostats, no polling.

Things to know:

- A thermostat accepts only about two connections at once. If the app is open
  on two phones and Home Assistant connects too, one of them may be refused.
- Pairing creates a key that lives only in Home Assistant's config entry. If
  you remove the integration, pair again with a new code.

## Installation (HACS)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=infestdead&repository=devireg-ha&category=integration)

1. HACS > Integrations > ⋮ > Custom repositories, add this repo as *Integration*.
2. Install **DEVIreg Smart** and restart Home Assistant.
3. Settings > Devices & services > Add integration > **DEVIreg Smart**.
4. In the DEVIsmart app, open Settings > Share house > Generate OTP, enter the
   code, and keep the app open until pairing finishes.

## Entities (per thermostat)

| Platform | Entities |
| --- | --- |
| Climate | Target temperature; Auto (weekly schedule), Heat (manual), Off; presets *At home* (until next schedule period), *Vacation*, *Pause (frost protection)* |
| Sensor | Room temperature, floor temperature, heating time (7 days, 30 days, total), energy in kWh (7 days, 30 days, total), heater power; Wi-Fi signal and relay switch count (diagnostic, disabled by default) |
| Binary sensor | Heating, window open; problems: sensor disconnected, sensor short circuit, overheat, unrecoverable error |
| Switch | Open window detection, forecast, screen lock, minimum floor temperature |
| Number | Comfort, economy, manual, vacation and frost protection temperatures; min/max floor temperature; low temperature warning; display brightness |

The climate entity's current temperature is the sensor the thermostat
regulates on (floor or room, from its installer setup); both readings are
also available as attributes.

Energy is estimated the same way the DEVIsmart app does it: heater on-time
multiplied by the heater power set during installation. Use *Energy (total)*
in the Energy dashboard. Thermostats wired to an external relay report no
power, so their energy sensors stay empty.

In Auto mode, changing the target temperature holds it until the next
schedule period (the app's "at home" override), rather than editing the
weekly comfort/economy setpoints. Those are available as number entities.

## Development

```bash
pip install pytest-homeassistant-custom-component PyNaCl
pytest
```

`custom_components/devireg/sdg/` is the SecureDeviceGrid client,
`dominion.py` the thermostat message format, `api.py` the house/thermostat
model, and the rest is Home Assistant glue.

## License

GPL-3.0, matching OpenSDG. SecureDeviceGrid is proprietary technology of
Trifork; this project is not affiliated with Danfoss and is for
non-commercial use only.

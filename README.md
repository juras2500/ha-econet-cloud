# PLUM ecoNET Cloud for Home Assistant

[Polski](README.pl.md) · [PV automation examples](examples/pv/README.md) · [Issues](https://github.com/juras2500/ha-econet-cloud/issues)

Community integration for the **econetcloud.eu** service. Monitor a ventilation unit and control the user settings supported by its profile. This project is independent of PLUM and SPIROFLEX.

## Tested hardware

- SPIROFLEX ventilation unit with **ecoVENT MINI OEM**, hardware H3.4.0, software S001.34.
- Internet module H1.1.0 / S005.04.
- Home Assistant Core **2026.11.2**, Python 3.14.

Other profiles may provide monitoring, but their controls are not confirmed. The control entities are created only when the expected ecoVENT MINI OEM user-profile layout is found. Optional sensors without hardware may remain unavailable.

## Features

- Supply, extract, intake and exhaust temperatures; actual airflows; humidity.
- Current speed, operating state, bypass, filter usage and remaining filter days.
- **Pause, Speed 1, Speed 2, Speed 3, Boost 1, Boost 2**.
- **Manual / Schedule** operating mode.
- Separate comfort-temperature settings for speeds 1–3, with limits reported by the controller.
- **End boost** without replacing the schedule.
- Transaction acknowledgment followed by fresh readback for every setting change; no optimistic success or automatic write retry.

Ordinary speeds and Pause require **Manual** mode. Boost can also be used with Schedule. Existing schedules stay on the controller; this integration does not edit them. External boost/fireplace signals are not overridden.

## Installation

### HACS custom repository

1. Open HACS / Marketplace and its custom-repository manager.
2. Add `https://github.com/juras2500/ha-econet-cloud`, category **Integration**.
3. Install **PLUM ecoNET Cloud** and restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → PLUM ecoNET Cloud**.
5. Sign in with the account used on **econetcloud.eu**, then select the installation.

This is a custom repository; it is not listed in the default HACS catalog.

### Manual installation

Copy `custom_components/econet_cloud` into your Home Assistant configuration's `custom_components` directory. Restart HA and add the integration as above. Install only one copy of the component.

## Account and connectivity

Use your **ecoNET Cloud account**, not an econet24.com account or a local ecoNET300 gateway password. The integration uses an outbound AWS IoT WebSocket and signed HTTPS requests. No MQTT broker, inbound port forwarding or separate AWS account is required. Internet/cloud availability is required.

Your password is used for SRP sign-in and is not saved. The HA server stores the account identifier, selected installation, refresh token and Cognito device key. A successful initial session may be cached privately for up to 15 minutes while setup is completed. Authentication data must never be added to source files or bug reports. Fixed AWS identifiers in `const.py` are public application configuration, not a user's private credentials.

## Dashboard

[`examples/dashboard.view.yaml`](examples/dashboard.view.yaml) is an optional view using native cards. Replace its `*.ventilation_*` placeholder entity IDs with the actual IDs from your device page. It includes controls, read-only tiles, filter gauges and 24-hour histories. It does not install itself or replace an existing dashboard.

## Heat-pump / PV examples

[`examples/pv`](examples/pv/README.md) contains two optional, separately enabled example packages: forecast-assisted DHW heating and a small, temporary space-heating comfort boost. They use placeholder entities and require adaptation. Installing this integration through HACS does **not** install or enable the packages.

The separate **ecoNET300** integration is maintained in [jontofront/ecoNET-300-Home-Assistant-Integration](https://github.com/jontofront/ecoNET-300-Home-Assistant-Integration), based on the original project by pblxptr. Its implementation is not included here.

## Troubleshooting and support

- Confirm that the unit is online in ecoNET Cloud and that you chose the right installation.
- A setting error means acknowledgment/readback was not confirmed. Check the actual unit state before retrying.
- Download integration diagnostics for message counters, recent operation statuses and supported control readings. Review diagnostics before sharing them.
- Report the controller model, hardware/software versions, HA version and a reproducible sequence in an issue. Never post credentials, session tokens, complete HA backups or private configuration files.

## Development

```sh
python -m venv .venv
# Activate the virtual environment, then:
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall -q custom_components
```

Tests use dummy credentials and synthetic protocol fixtures. They do not sign in to a real account or change a real controller. See [CHANGELOG.md](CHANGELOG.md) for the initial live-verification scope and [NOTICE](NOTICE) for references and attribution.

## License

MIT — see [LICENSE](LICENSE). The license covers this repository's original code and examples; dependency licenses and manufacturer trademarks remain with their respective owners.

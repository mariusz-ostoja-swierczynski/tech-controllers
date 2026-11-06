# :jigsaw: TECH Controllers integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![Project Maintenance][maintenance-shield]][maintainer]

This is an integration of heating controllers from Polish company TECH Sterowniki Sp. z o.o. It uses [API](https://api-documentation.emodul.eu/) to their web control application eModul.eu, therefore your controller needs to be accessible from the Internet and you need an account either on <https://emodul.eu> or <https://emodul.pl>.

The integration is based on API provided by TECH which supports the [list of compatible controllers](https://github.com/mariusz-ostoja-swierczynski/tech-controllers?tab=readme-ov-file#rocket-list-of-reported-working-tech-controllers)

The integration was developed and tested against eModul demo account (username: `test`/password: `test`) which features 4 controllers:

- I-3
- L-8
- Pellet
- Solar

and community reported controllers.

> [!WARNING]
> Everything else might or might not work - needs community help, testing and reporting back what works. Check below for reported working controllers.

## :sparkles: Features

- Configuration through UI
- Support for multiple controllers which can be individually imported under given single account
- Provides Climate entities representing zones
  - and their corresponding Temperature, Battery, Humidity sensors, Window sensors when available
- Climate entities display data through Thermostat card
- Limited support for Menu handling (thanks [lhruska](https://github.com/lhruska)!)
- Reads the installer and service menus of controllers that keep them behind a code (see [Menu codes](#menu-codes))
- Provides sensors for eModul 'tiles'
- Automatic naming and translations of tiles from eModul API
- Supporting languages which are supported by eModul API

**This integration will set up the following platforms.**

| Platform        | Description                         |
| --------------- | ----------------------------------- |
| `binary_sensor` | Show info and status from Tech API. |
| `sensor`        | Show info and status from Tech API. |
| `climate`       | Thermostats.                        |
| `button`        | Button for dialogue menu items.     |
| `switch`        | Switch for menu parameters.         |
| `number`        | Number for menu parameters.         |
| `select`        | Select for menu parameters.         |

### Read-only zone schedules

Controllers that report zone schedules, including M-9r, expose three additional
climate attributes: `schedule_mode`, `schedule_index` and `active_schedule_name`.
An active name requires a complete, valid schedule and confirmed Normal mode;
Holiday, Eco, Comfort, pending changes and failed updates suppress that name.
A local schedule without a supplied name keeps the name empty. A controller is
treated as schedule-capable when the payload exposes global template elements
or a zone mode/schedule object, even if every zone is currently in
constant-temperature mode.

The zone also has a read-only **Schedule** sensor, enabled by default. Its state
is the proven active schedule name, falling back to the configured mode
(`globalSchedule`, `localSchedule`, `constantTemp`, ...). Its attributes carry
the selected and local templates, applicability, validity and errors.

The **Local schedule** sensor per zone and the **Global schedule N** sensors per
controller are disabled by default. All five global slots are created up front;
a slot without a template reports `missing` and becomes valid without a reload
once the controller adds it. They report `valid`, `pending`, `invalid` or
`missing`, with the Monday-first week, `HH:MM` interval times, Celsius
temperatures and decoding errors. Intervals ending at midnight are displayed as
`24:00`; the controller's `stop: 0` is treated as midnight. A controller-level **Schedules** diagnostic
sensor, disabled by default, reports `ready`, `partial` or `missing`; its compact
attributes summarize selection and errors without duplicating the template
graphs. A **Schedule problem** binary sensor, enabled by default, turns on only
when a selected template is missing or invalid. Raw controller payloads are not
exposed.

These are read-only configuration details from the existing poll. They add no
API requests, do not change schedules or targets, and do not calculate the current
or next target from the controller's clock.

### Menu codes

Some controllers keep their installer and service menus behind a numeric code.
The service menu is the deep one, and it is where a heat pump keeps controls an
installer would use — clearing a pressure-switch lockout, for example. The API
refuses to serve such a menu at all until it is given the code, and its refusal
says nothing about which code it wants, so the code can only be entered by hand.

The config flow asks for one code per menu — user (`MU`), installer (`MI`) and
service (`MS`) — right after you pick your controllers. The manufacturer menu
(`MP`) is not asked about: it is refused on every consumer account, so a code
would not help. Every field is optional: leave a field empty if you have no code
for that menu, and the integration behaves exactly as it did before, since a
field left empty stores no code at all. Two things are worth knowing:

- A wrong code looks exactly like no code. The API refuses the menu either way
  with the same answer, so a mistyped code cannot be told apart from a missing
  one — it simply does not unlock anything.
- To change or remove a code, remove the integration entry and add it again.

If a code you entered is not accepted, Home Assistant raises a repair issue
naming that menu. Menus that simply cannot be read are not reported: on a
consumer account that is normal for several of them.

![Tech Thermostat Cards](./images/ha-tech-1.png)

## :building_construction: Installation

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mariusz-ostoja-swierczynski&repository=tech-controllers&category=integration)

### Manual

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. Download `tech.zip` asset from [latest release](https://github.com/mariusz-ostoja-swierczynski/tech-controllers/releases/latest)
1. Unzip into `custom_components/` directory (folder), if directory doesnt exist, create it.
1. Restart Home Assistant
1. In the HA UI go to `Configuration` -> `Integrations` click `+` and search for `Tech Controllers`
   ![Tech Controllers Setup 1](./images/ha-tech-add-integration-1.png)
1. Enter your username (could be email) and password for your eModule account and click "Submit" button.
   ![Tech Controllers Setup 2](./images/ha-tech-add-integration-2.png)
1. In the next step select the controllers you want to import/integrate
   ![Tech Controllers Setup 3](./images/ha-tech-add-integration-3.png)
1. You should see "Success!" dialog with the name of the imported controller(s).
   ![Tech Controllers Setup 3](./images/ha-tech-add-integration-4.png)

1. Now you should have controllers and entities representing your home zones available in Home Assistant. Go to your UI Lovelace configuration and add Thermostat card with your Climate entities.
   ![Tech Controllers Setup 4](./images/ha-tech-2.png)

## :rocket: List of reported working TECH Controllers

- L-7 (v.2.0.8)
- L-7E (v.1.0.6)
- L-8 (v.3.0.14)
- L-9r (v1.0.2)
- L-12 (v.1.0.16)
- L4-WiFi (v.1.0.24)
- L-X WiFi (v1.0.6)
- M-9 (v1.0.12)
- M-9r (v1.3.8)
- ST-8s WIFI (v.1.0.5)
- ST-16s WIFI (v.1.0.5)
- ST-491 (v.2.1.9) -- RS-bridged boiler controllers; CH/DHW/room temperatures, valve, fuel feeder, fan, pumps, disinfection cycle and relays exposed
- ST-505 -- same RS-bridged-boiler family as ST-491; supported via the shared TYPE_WIDGET tile parser
- WiFi 8S (v.2.1.8)

## :pray: Thanks

Version 2 of the integration is based on work from several contributors and/or forks of the original integration:

- [MichalKrasowski](https://github.com/MichalKrasowski)
- [micles123](https://github.com/micles123)
- [nedyarrd](https://github.com/nedyarrd)
- [anarion80](https://github.com/anarion80)
- others

## :warning: Disclaimer

The integration is in no way supported or endorsed by TECH Sterowniki sp. z o.o.

## 📝 Copyright & License

Copyright (c) 2026, Released under the [MIT](LICENSE) license.

---

[commits-shield]: https://img.shields.io/github/commit-activity/y/custom-components/blueprint.svg?style=for-the-badge
[commits]: https://github.com/mariusz-ostoja-swierczynski/tech-controllers/commits/main
[license-shield]: https://img.shields.io/github/license/mariusz-ostoja-swierczynski/tech-controllers?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/current%20maintainer-anarion80-blue.svg?style=for-the-badge
[maintainer]: https://github.com/anarion80
[releases-shield]: https://img.shields.io/github/release/mariusz-ostoja-swierczynski/tech-controllers.svg?style=for-the-badge
[releases]: https://github.com/mariusz-ostoja-swierczynski/tech-controllers/releases

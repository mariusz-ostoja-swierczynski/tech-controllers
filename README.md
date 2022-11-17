# TECH Controllers integration for Home Assistant
The integration of heating controllers from Polish company TECH Sterowniki Sp. z o.o. It uses API to their web control application eModul.eu, therefore your controller needs to be accessible from internet and you need an account either on https://emodul.eu or https://emodul.pl.

The integration is based on eModule API which lists support only following controllers, but many other were reported working. Please see the list at end of this page or visit [issue #2](https://github.com/mariusz-ostoja-swierczynski/tech-controllers/issues/2):

* L-7
* L-8
* WiFi 8S
* ST-8S WiFi

Please report within [this issue](https://github.com/mariusz-ostoja-swierczynski/tech-controllers/issues/2) if this integration works with your controller and what version.

## Disclaimer
This is my first integration ever developed for Home Assistant, and although I don't see any way how this software can harm your devices, you are using it on your own risk and I do not provide any warranties.

## Features
* Configuration through Integrations (not via configuration.yaml)
* Support for multiply controllers (thanks to @mariusz-ostoja-swierczynski)
  * Integration during setup iterates through all controllers in the system and adds supported entities specified below. 
* Support for following devices and entities aka tiles (thanks to @alevike, @gszumiec and @maciej-or work :clap:):
  * Temperature Sensor
  * CH Temperature Sensor
  * Fan Rotations Sensor (in percentage)
  * Valve Opening Sensor (in percentage)
  * Fuel Supply Sensor (in percentage)
  * State Sensor (text information ex. for pump modes or controller state)
  * Relay Working Sensor (true of false ex. for feeders, pumps, heater)
  ![Tech Devices](/custom_components/tech/images/ha-tech-devices.png)
* Provides Climate entities with Thermostat card representing zones in household:
  * Displays zone name
  * Displays current zone temperature
  * Controls target zone temperature
  * Displays current zone state (heating or idle)
  * Controls and displays zone mode (on or off)
  ![Tech Thermostat Cards](/custom_components/tech/images/ha-tech-1.png)
* Support for multiply languages (thanks to @maciej-or work 👍:clap:):
  * English
  * Polish
  * German
  * Hungarian
  * Slovak
  * Russian

## Installation

1. Copy entire repository content into your config/custom_components/tech folder of your Home Assistant installation.  
   **Note:** If you don't have in your installation "custom_components" folder you need to create one and "tech" folder in it.
2. Restart Home Assistant.
3. Go to Configuration -> Integrations and click Add button.
4. Search for "Tech Controllers" integration and select it.
5. Enter your username (could be email) and password for your eModule account and click "Submit" button.
6. You should see "Success!" dialog with a name and version of your main Tech controller.  
   **Note:** The integration currently supports handling only one controller. If the API returns list of more than one controllers in your household, the only first one will be used.
7. Now you should have Climate entities representing your home zones available in Home Assistant. Go to your UI Lovelace configuration and add Thermostat card with your Climate entities. 

![Tech Controllers Setup 1](/custom_components/tech/images/ha-tech-add-integration-1.png)

![Tech Controllers Setup 2](/custom_components/tech/images/ha-tech-add-integration-2.png)

![Tech Controllers Setup 3](/custom_components/tech/images/ha-tech-add-integration-3.png)

![Tech Controllers Setup 4](/custom_components/tech/images/ha-tech-add-integration-4.png)

![Tech Controllers Setup 5](/custom_components/tech/images/ha-tech-2.png)

## List of reported working TECH Controllers 
* L4-WiFi (v.1.0.24)
* L7 (v.2.0.6)
* L-7 (v.2.0.8)
* L-7E (v.1.0.6)
* L-8 (v.3.0.14)
* L-9r (v1.0.2)
* WiFi 8S (v.2.1.8)
* ST-8s WIFI (v.1.0.5)
* ST-16s WIFI (v.1.0.5)
* M-9 (v1.0.12)
* M-9r (v.1.1.11)
* I-2
* EU-L-4 with EU-MW-1

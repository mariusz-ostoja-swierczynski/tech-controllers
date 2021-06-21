# TECH Controllers integration for Home Assistant
The integration of heating controllers from Polish company TECH Sterowniki Sp. z o.o. It uses API to their web control application eModul.eu, therefore your controller needs to be accessible from internet and you need an account either on https://emodul.eu or https://emodul.pl.

The integration is based on API provided by TECH which supports following controllers:
* L-7
* L-8
* WiFi 8S
* ST-8S WiFi

Unfortunately, I own only L-8 controller based on which it was developed and tested. Therefore, please report within [this issue](https://github.com/mariusz-ostoja-swierczynski/tech-controllers/issues/2) if this integration works with your controller and what version.

## Disclaimer
This is my first integration ever developed for Home Assistant, and although I don't see any way how this software can harm your devices, you are using it on your own risk and I do not provide any warranties.

## Features
* Configuration through Integrations (not via configuration.yaml)
* Provides Climate entities representing zones in household
* Climate entities displays data through Thermostat card
* Displays zone name
* Displays current zone temperature
* Controls target zone temperature
* Displays current zone state (heating or idle)
* Controls and displays zone mode (on or off)

![Tech Thermostat Cards](/custom_components/tech/images/ha-tech-1.png)

## Plans for development
* Support for multiply controllers
* Publish the tech.py Python Package to PyPI
* Write tests for HA component
* Support for window opening sensor
* Support for cold tolerance setting
* Support for zones schedules

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

![Tech Controllers Setup 4](/custom_components/tech/images/ha-tech-2.png)

## List of reported working TECH Controllers 
* L4-WiFi (v.1.0.24)
* L-7 (v.2.0.8)
* L-7E (v.1.0.6)
* L-8 (v.3.0.14)
* L-9r (v1.0.2)
* WiFi 8S (v.2.1.8)
* ST-8s WIFI (v.1.0.5)
* ST-16s WIFI (v.1.0.5)
* M-9 (v1.0.12)

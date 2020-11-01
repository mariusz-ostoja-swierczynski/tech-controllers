# Tech Controllers integration for Home Assistant
The integration of heating controllers from Polish company TECH Sterowniki Sp. z o.o. It uses API to their web control application eModule.eu therefore your controller needs to be accessible from internet and you need account either on https://emodule.eu or https://emodule.pl.

## Disclaimer
This is my first integration ever developed for Home Assistant, and although I don't see any way how this software can harm your devices, you are using in on your own risk and I do not provide any warranties.

## Features
* Configuration through Integrations (not via configuration.yaml)
* Provides Climate entities representing zones in household
* Climate entities displays data through Thermostat card
* Displays zone name
* Displays current zone temperature
* Controls target zone temperature
* Displays current zone state (heating or idle)
* Controls and displays zone mode (on or off)

![Tech Thermostat Cards](/images/ha-tech-1.png)

## Installation

1. Copy entire "tech" folder into your config/custom_components folder of your Home Assistant installation.
2. Restart Home Assistant.
3. Go to Configuration -> Integrations and click Add button.
4. Search for "Tech Controllers" integration and select it.
5. Enter your username (could be email) and password for your eModule account and click "Submit" button.
6. You should see "Success!" dialog with a name and version of your main Tech controller.
    **Note:** The integration currently supports handling only one controller. If the API returns list of more than one controllers in your household, the only first one will be used.
7. Now you should have Climate entities representing your home zones available in Home Assistant. Go to your UI Lovelace configuration and add Thermostat card with your Climate entities. 

![Tech Controllers Setup 1](/images/ha-tech-add-integration-1.png)

![Tech Controllers Setup 2](/images/ha-tech-add-integration-2.png)

![Tech Controllers Setup 3](/images/ha-tech-add-integration-3.png)

![Tech Controllers Setup 4](/images/ha-tech-2.png)
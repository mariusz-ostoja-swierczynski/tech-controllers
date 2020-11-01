# Tech Controllers integration for Home Assistant
The integration of heating controllers from polish company TECH Sterowniki Sp. z o.o. It uses API to thier web control application eModule.eu therefore your controller needs to be accessible from internet and you need account either on https://emodule.eu or https://emodule.pl.

## Disclaimer
This is my first integration ever developed for Home Assistant, and although I don't see any way how this software can harm your devices, you are using in on your own risk and I do not provide any warranties.

## Featurs
* Configuration through Integrations (not via configuration.yaml)
* Provides Climate entities representing zones in household
* Climate entities displays data through Thermostat card
* Displays zone name
* Displays current zone temperature
* Controls target zone temperature
* Displays current zone state (heating or idle)
* Controls and displays zone mode (on or off)

## Installation

1. Copy entier "tech" folder into your config/custom_components foler of your Home Assistant installation.
2. Restart Home Assistant.
3. Go to Configuration -> Integrations and click Add button.
4. Search for "Tech Controllers" integration and select it.
5. Enter your username (could be email) and password for your eModule account and click "Submit" button.
6. You should see "Success!" dialog with a name and version of your main Tech contorller.
    **Note:** The integration currently supports handling only one controller. If the API returns list of more then one controllers in your household, the only first one will be used.
7. Now you should have Climate entities representing your home zones available in Home Assistant. Go to your UI Lovelace configuration and add Thermostat card with your Climate entities. 

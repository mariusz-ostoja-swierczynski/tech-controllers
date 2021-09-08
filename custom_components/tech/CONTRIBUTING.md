# Contributing to TECH Controllers integration for Home Assistant

:+1::tada: First off all, many thanks for taking the time to contribute! Appreciated! :tada::+1:

The following is a set of guidelines for contributing to this integration. These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Reporting Bugs

This section guides you through submitting a bug report for the integration. Following these guidelines helps maintainers and the community understand your report, reproduce the behavior, and find related reports.

Before creating bug reports, please check [this issues list](https://github.com/mariusz-ostoja-swierczynski/tech-controllers/issues) as you might find out that you don't need to create one. When you are creating a bug report, please **include as many details as possible**:

* **Use a clear and descriptive title** for the issue to identify the problem.
* **Describe the exact steps which reproduce the problem** in as many details as possible.
* **Provide specific examples to demonstrate the steps**.
* **Describe the behavior you observed after following the steps** and point out what exactly is the problem with that behavior.
* **Explain which behavior you expected to see instead and why.**
* **Please try to include logs**

### Getting logs from your Home Assistant

1. Enable debug logs for "tech" component by adding following to your configuration.yaml file within config folder:
```yaml
logger:
  default: info
  logs:
    homeassistant.components.tech: debug
```
2. Restart your Home Assistant.

3. Go to **Developer Tools** from left menu, then **LOGS** tab and press **LOAD FULL HOME ASSISTANT LOG** button.

![HA TECH LOGS](/images/ha-tech-logs.png)

4. Search for a place with homeassistant.components.climate or homeassistant.components.tech or just climate, copy it and add to the reported issue.

![HA TECH LOGS EXAMPLE](/images/ha-tech-logs-ex.png)

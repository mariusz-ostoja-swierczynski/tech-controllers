"""Home Assistant actions that change a zone's mode on the controller.

The actions only select or write what the controller already reports: they do
not edit, create or rename schedule templates, and they never refresh the
coordinator. The next poll reconciles the zone with the controller.
"""

# allow: SIZE_OK — one cohesive service surface (two actions, their schemas,
# target resolution, error translation) whose every function carries the
# mandated Google-style docstring; splitting it needs a module outside scope.

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import logging
from typing import Any, cast

import voluptuous as vol

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    target as target_helpers,
)
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.helpers.translation import async_get_translations

from .const import CONTROLLER, DOMAIN, UDID
from .coordinator import TechCoordinator
from .schedules import (
    SCHEDULE_INDEX_MAX,
    SCHEDULE_INDEX_MIN,
    ScheduleSelectionError,
    global_schedule_index_by_name,
    global_schedule_write,
    local_schedule_write,
    zone_mode_id,
)
from .tech import TechError

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_ZONE_SCHEDULE = "set_zone_schedule"
SERVICE_SET_ZONE_CONSTANT = "set_zone_constant"

# The computed options live in ``hass.data`` rather than in a module global: a
# test creates several Home Assistant instances in one process, and a global
# would carry one instance's controllers into the next one's dropdown.
SCHEDULE_SERVICE_SCHEMA_CACHE = f"{DOMAIN}_schedule_service_schema"

ATTR_SCHEDULE = "schedule"
ATTR_SOURCE = "source"
ATTR_INDEX = "index"
ATTR_DURATION_MINUTES = "duration_minutes"

# A zone climate entity reports ``{udid}_{zone_id}_zone_climate`` as its unique
# id, and the zone's schedule select reports
# ``{udid}_{zone_id}_zone_schedule_select``. Either carries both the controller
# and the zone the action has to write to.
ZONE_CLIMATE_SUFFIX = "_zone_climate"
ZONE_SCHEDULE_SELECT_SUFFIX = "_zone_schedule_select"
ZONE_TARGET_SUFFIXES = (ZONE_CLIMATE_SUFFIX, ZONE_SCHEDULE_SELECT_SUFFIX)

SET_ZONE_SCHEDULE_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Optional(ATTR_SCHEDULE): vol.All(str, vol.Length(min=1)),
        vol.Optional(ATTR_SOURCE): vol.In(["global", "local"]),
        vol.Optional(ATTR_INDEX): vol.All(
            vol.Coerce(int),
            vol.Range(min=SCHEDULE_INDEX_MIN, max=SCHEDULE_INDEX_MAX),
        ),
    }
)

SET_ZONE_CONSTANT_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=5, max=35)
        ),
        vol.Optional(ATTR_DURATION_MINUTES, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=1440)
        ),
    }
)

# The helper's stable reason names, translated for the user. An unknown reason
# would mean a bug in the helper, so it is reported as an invalid schedule
# rather than leaking a key that has no translation.
_SCHEDULE_ERROR_KEYS = {
    "unsupported": "schedule_unsupported",
    "missing": "schedule_not_found",
    "not_settled": "schedule_not_settled",
    "invalid": "schedule_invalid",
    "mode_missing": "zone_mode_missing",
    "name_not_found": "schedule_name_not_found",
    "name_ambiguous": "schedule_name_ambiguous",
}

# English fallbacks, kept in step with the translated exception messages. They
# make str(error) useful before the translation is loaded or when a key is
# missing from an older translation file.
_SCHEDULE_ERROR_MESSAGES = {
    "schedule_unsupported": "This controller does not report zone schedules.",
    "schedule_not_found": "This zone has no {source} schedule to activate.",
    "schedule_not_settled": (
        "The controller is still applying a change to this schedule. "
        "Try again shortly."
    ),
    "schedule_invalid": (
        "The selected schedule is incomplete or invalid, so it cannot be "
        "activated."
    ),
    "zone_mode_missing": (
        "The controller did not report the zone's mode identifier."
    ),
    "schedule_name_not_found": (
        "No global schedule is named {name} on this controller."
    ),
    "schedule_name_ambiguous": (
        "More than one global schedule is named {name}; use the legacy index "
        "instead."
    ),
}

# A target plus the payload that was validated for it before any write started.
type _PreparedWrite = tuple[TechCoordinator, int, dict[str, Any]]


def _schedule_error(
    error: ScheduleSelectionError, source: str, name: str | None = None
) -> HomeAssistantError:
    """Translate a schedule preparation failure into a service error.

    Args:
        error: Failure raised while preparing a write.
        source: Selected schedule source, used by the missing-schedule message.
        name: Entered schedule name, used by the name lookup messages.

    Returns:
        The translated error the service call raises.

    """
    key = _SCHEDULE_ERROR_KEYS.get(error.reason, "schedule_invalid")
    placeholders: dict[str, str] = {}
    if key == "schedule_not_found":
        placeholders = {"source": source}
    elif key in ("schedule_name_not_found", "schedule_name_ambiguous"):
        placeholders = {"name": name or ""}
    message = _SCHEDULE_ERROR_MESSAGES[key].format(**placeholders)
    return HomeAssistantError(
        message,
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


def _controller_udid(coordinator: TechCoordinator) -> str:
    """Return the controller identifier of an already resolved target.

    Args:
        coordinator: Coordinator of the target's config entry.

    Returns:
        The controller udid stored in the entry.

    Raises:
        HomeAssistantError: If the resolved entry has no controller udid;
            target resolution already rejects such an entry.

    """
    controller = coordinator.config_entry.data.get(CONTROLLER)
    udid = controller.get(UDID) if isinstance(controller, Mapping) else None
    if not isinstance(udid, str):
        raise HomeAssistantError(
            "Target a Tech climate entity (a zone thermostat).",
            translation_domain=DOMAIN,
            translation_key="zone_target_invalid",
        )
    return udid


def _resolve_targets(
    hass: HomeAssistant, call: ServiceCall
) -> list[tuple[TechCoordinator, int]]:
    """Resolve entity, device, area, floor and label targets to their zones.

    Home Assistant expands every target form through its target helpers before
    the Tech-entity filter runs. A Tech climate entity and the zone's schedule
    select entity each carry both the controller and the zone in their unique
    id; sibling entities of the same zone device are ignored, so a zone device
    target still resolves through its climate entity.

    Args:
        hass: Home Assistant instance.
        call: Service call whose target names the zones.

    Returns:
        One ``(coordinator, zone_id)`` entry per distinct target.

    Raises:
        HomeAssistantError: If no target is a Tech climate entity.

    """
    selection = target_helpers.TargetSelection(call.data)
    if selection.has_any_target:
        referenced = target_helpers.async_extract_referenced_entity_ids(
            call.hass, selection
        )
        entity_ids = sorted(referenced.referenced | referenced.indirectly_referenced)
    else:
        entity_ids = []

    registry = er.async_get(hass)
    targets: list[tuple[TechCoordinator, int]] = []
    seen: set[tuple[str, int]] = set()

    for entity_id in entity_ids:
        registry_entry = registry.async_get(entity_id)
        if registry_entry is None or registry_entry.platform != DOMAIN:
            continue
        unique_id = registry_entry.unique_id
        matched_suffix = next(
            (suffix for suffix in ZONE_TARGET_SUFFIXES if unique_id.endswith(suffix)),
            None,
        )
        if matched_suffix is None:
            continue
        udid, separator, zone_part = unique_id[: -len(matched_suffix)].rpartition(
            "_"
        )
        if not separator or not zone_part.isdigit():
            continue
        zone_id = int(zone_part)

        config_entry_id = registry_entry.config_entry_id
        if config_entry_id is None:
            continue
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None:
            continue
        runtime_data = getattr(entry, "runtime_data", None)
        if not isinstance(runtime_data, TechCoordinator):
            continue
        coordinator = runtime_data
        if not isinstance(coordinator.data, dict):
            continue

        controller = entry.data.get(CONTROLLER)
        expected_udid = controller.get(UDID) if isinstance(controller, Mapping) else None
        if not isinstance(expected_udid, str) or udid != expected_udid:
            continue

        key = (entry.entry_id, zone_id)
        if key in seen:
            continue
        seen.add(key)
        targets.append((coordinator, zone_id))

    if not targets:
        raise HomeAssistantError(
            "Target a Tech climate entity (a zone thermostat).",
            translation_domain=DOMAIN,
            translation_key="zone_target_invalid",
        )
    return targets


def _write_error(error: TechError) -> HomeAssistantError:
    """Translate a controller refusal into a service error.

    Args:
        error: Refusal returned by the Tech client.

    Returns:
        The translated error the service call raises.

    """
    return HomeAssistantError(
        f"The controller refused the zone change: {error.status}",
        translation_domain=DOMAIN,
        translation_key="zone_write_failed",
        translation_placeholders={"error": str(error.status)},
    )


async def _async_set_zone_schedule(call: ServiceCall) -> None:
    """Switch one or more zones to a named global or a local schedule.

    ``schedule`` names a configured global template (or ``local``) and takes
    precedence over the legacy ``source``/``index`` fields. ``index`` still
    selects a global template by slot. Every target is validated before the
    first write, so a selection that cannot be prepared leaves the controller
    untouched.

    Args:
        call: Home Assistant service call.

    Raises:
        HomeAssistantError: If a target is not a Tech zone entity, the call
            names no schedule, a global selection omits both a name and an
            index, the snapshot cannot be prepared for a write, or the
            controller refuses it.

    """
    schedule = cast("str | None", call.data.get(ATTR_SCHEDULE))
    source = cast("str | None", call.data.get(ATTR_SOURCE))
    index = cast("int | None", call.data.get(ATTR_INDEX))
    name: str | None = None

    if schedule is not None:
        name = schedule.strip()
        if not name:
            raise HomeAssistantError(
                "Choose a schedule name, or `local`, or use the legacy source "
                "and index fields.",
                translation_domain=DOMAIN,
                translation_key="schedule_selection_required",
            )
        if name.casefold() == "local":
            source = "local"
            index = None
            name = None
        else:
            source = "global"
    elif source is None:
        raise HomeAssistantError(
            "Choose a schedule name, or `local`, or use the legacy source and "
            "index fields.",
            translation_domain=DOMAIN,
            translation_key="schedule_selection_required",
        )
    elif source == "global" and index is None:
        raise HomeAssistantError(
            "A global schedule selection needs an index between 0 and 4.",
            translation_domain=DOMAIN,
            translation_key="schedule_index_required",
        )

    targets = _resolve_targets(call.hass, call)
    try:
        prepared: list[_PreparedWrite] = []
        for coordinator, zone_id in targets:
            snapshot = coordinator.data.get("schedules")
            if source == "global":
                selected_index = (
                    global_schedule_index_by_name(snapshot, name)
                    if name is not None
                    else cast("int", index)
                )
                payload = global_schedule_write(snapshot, zone_id, selected_index)
            else:
                payload = local_schedule_write(snapshot, zone_id)
            prepared.append((coordinator, zone_id, payload))
    except ScheduleSelectionError as err:
        raise _schedule_error(err, source, name) from err

    try:
        for coordinator, zone_id, payload in prepared:
            udid = _controller_udid(coordinator)
            if source == "global":
                await coordinator.api.set_zone_global_schedule(
                    udid,
                    zone_id,
                    payload["mode_id"],
                    payload["schedule"],
                    payload["schedule_name"],
                    payload["set_in_zones"],
                )
            else:
                await coordinator.api.set_zone_local_schedule(
                    udid, zone_id, payload["mode_id"], payload["schedule"]
                )
            _LOGGER.debug("Set zone %s to the %s schedule", zone_id, source)
    except TechError as err:
        raise _write_error(err) from err


async def _async_set_zone_constant(call: ServiceCall) -> None:
    """Set a zone to a constant temperature, permanently or for a limited time.

    A duration of ``0`` keeps the temperature until it is changed; a positive
    duration limits it to that many minutes. Every target is checked for a
    reported mode id before the first write.

    Args:
        call: Home Assistant service call.

    Raises:
        HomeAssistantError: If a target is not a Tech climate entity, the
            controller reports no mode id for a zone, or the controller
            refuses the write.

    """
    temperature = cast("float", call.data[ATTR_TEMPERATURE])
    duration = cast("int", call.data.get(ATTR_DURATION_MINUTES, 0))

    targets = _resolve_targets(call.hass, call)
    prepared: list[tuple[TechCoordinator, int, int]] = []
    for coordinator, zone_id in targets:
        mode_id = zone_mode_id(coordinator.data.get("schedules"), zone_id)
        if mode_id is None:
            raise HomeAssistantError(
                "The controller did not report the zone's mode identifier.",
                translation_domain=DOMAIN,
                translation_key="zone_mode_missing",
            )
        prepared.append((coordinator, zone_id, mode_id))

    try:
        for coordinator, zone_id, mode_id in prepared:
            await coordinator.api.set_zone_constant(
                _controller_udid(coordinator),
                zone_id,
                mode_id,
                temperature,
                duration or None,
            )
            _LOGGER.debug("Set zone %s to a constant temperature", zone_id)
    except TechError as err:
        raise _write_error(err) from err


async def async_update_schedule_service_schema(hass: HomeAssistant) -> None:
    """Refresh the set_zone_schedule dropdown from the loaded controllers.

    The options are every configured global schedule name the loaded
    controllers report, plus ``local``. A name that appears more than once on
    one controller is left out, because the service cannot tell those templates
    apart by name; the legacy ``source``/``index`` fields still select them.

    Args:
        hass: Home Assistant instance.

    """
    names: list[str] = []
    ambiguous: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data = getattr(entry, "runtime_data", None)
        if not isinstance(runtime_data, TechCoordinator):
            continue
        data = runtime_data.data
        if not isinstance(data, dict):
            continue
        snapshot = data.get("schedules")
        globals_ = (
            snapshot.get("globalSchedules") if isinstance(snapshot, dict) else None
        )
        elements = globals_.get("elements") if isinstance(globals_, dict) else None
        if not isinstance(elements, list):
            continue
        templates = [
            (item["index"], item["name"])
            for item in elements
            if isinstance(item, dict)
            and type(item.get("index")) is int
            and isinstance(item.get("name"), str)
            and item["name"]
        ]
        counts = Counter(template_name.casefold() for _, template_name in templates)
        ambiguous.update(
            folded for folded, count in counts.items() if count > 1
        )
        names.extend(template_name for _, template_name in templates)

    unique: dict[str, str] = {}
    for template_name in names:
        folded = template_name.casefold()
        if folded not in ambiguous:
            unique.setdefault(folded, template_name)
    sorted_names = tuple(sorted(unique.values(), key=str.casefold))

    translations = await async_get_translations(
        hass, hass.config.language, "entity", [DOMAIN]
    )
    local_label = translations.get(
        "component.tech.entity.sensor.zone_schedule_entity.state.local-schedule",
        "Local Schedule",
    )
    service_translations = await async_get_translations(
        hass, hass.config.language, "services", [DOMAIN]
    )
    service_name = service_translations.get(
        "component.tech.services.set_zone_schedule.name", "Set zone schedule"
    )
    description = service_translations.get(
        "component.tech.services.set_zone_schedule.description", ""
    )

    current = (sorted_names, local_label, service_name, description)
    if hass.data.get(SCHEDULE_SERVICE_SCHEMA_CACHE) == current:
        return

    options = [{"value": "local", "label": local_label}]
    options.extend(
        {"value": template_name, "label": template_name}
        for template_name in sorted_names
    )
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_SET_ZONE_SCHEDULE,
        {
            "name": service_name,
            "description": description,
            "target": {"entity": {"integration": DOMAIN, "domain": "climate"}},
            "fields": {
                "schedule": {
                    "required": True,
                    "example": "Weekend",
                    "selector": {"select": {"options": options, "mode": "dropdown"}},
                }
            },
        },
    )
    hass.data[SCHEDULE_SERVICE_SCHEMA_CACHE] = current


async def async_register_services(hass: HomeAssistant) -> None:
    """Register the two zone-mode actions once for the integration.

    Args:
        hass: Home Assistant instance.

    """
    if hass.services.has_service(
        DOMAIN, SERVICE_SET_ZONE_SCHEDULE
    ) or hass.services.has_service(DOMAIN, SERVICE_SET_ZONE_CONSTANT):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ZONE_SCHEDULE,
        _async_set_zone_schedule,
        schema=SET_ZONE_SCHEDULE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ZONE_CONSTANT,
        _async_set_zone_constant,
        schema=SET_ZONE_CONSTANT_SCHEMA,
    )

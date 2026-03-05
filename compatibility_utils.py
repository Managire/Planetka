import bpy

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS

PLANETKA_VIEWPORT_DICING_TARGET = 2.0


def _set_enum_property_safe(owner, prop_name, preferred_identifiers):
    if owner is None or not hasattr(owner, prop_name):
        return False

    available = set()
    try:
        prop_def = owner.bl_rna.properties.get(prop_name)
        if prop_def and hasattr(prop_def, "enum_items"):
            available = {item.identifier for item in prop_def.enum_items}
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        available = set()

    for identifier in preferred_identifiers:
        if available and identifier not in available:
            continue
        try:
            current = getattr(owner, prop_name, None)
            if current == identifier:
                return False
            setattr(owner, prop_name, identifier)
            return True
        except PLANETKA_RECOVERABLE_EXCEPTIONS:
            continue
    return False


def _clamp_cycles_viewport_dicing(scene, target=PLANETKA_VIEWPORT_DICING_TARGET):
    if scene is None:
        return False
    cycles = getattr(scene, "cycles", None)
    if cycles is None or not hasattr(cycles, "preview_dicing_rate"):
        return False
    try:
        current = float(getattr(cycles, "preview_dicing_rate", float(target)))
    except (PLANETKA_RECOVERABLE_EXCEPTIONS, TypeError, ValueError):
        return False
    if current <= float(target):
        return False
    try:
        cycles.preview_dicing_rate = float(target)
        return True
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return False


def ensure_adaptive_subdivision_compat(scene, return_details=False):
    changed = False
    viewport_dicing_adjusted = False

    if scene is not None:
        cycles = getattr(scene, "cycles", None)
        if cycles is not None:
            changed |= _set_enum_property_safe(cycles, "feature_set", ("EXPERIMENTAL",))
        viewport_dicing_adjusted = _clamp_cycles_viewport_dicing(scene)
        changed = changed or viewport_dicing_adjusted

    earth_material = bpy.data.materials.get("Planetka Earth Material")
    if earth_material is not None:
        cycles_settings = getattr(earth_material, "cycles", None)
        if cycles_settings is not None:
            changed |= _set_enum_property_safe(
                cycles_settings,
                "displacement_method",
                ("DISPLACEMENT", "BOTH", "DISPLACEMENT_BUMP"),
            )

    if return_details:
        return {
            "changed": bool(changed),
            "viewport_dicing_adjusted": bool(viewport_dicing_adjusted),
        }
    return changed

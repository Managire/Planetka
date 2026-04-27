def iter_scenes(bpy_module):
    return tuple(getattr(bpy_module.data, "scenes", ()))


def _coerce_storage_value(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return value


def _iter_sync_idprop_pairs(sync_idprop_map, prop_names=None):
    if prop_names is None:
        for prop_name, scene_key in sync_idprop_map.items():
            yield prop_name, scene_key
        return

    if isinstance(prop_names, str):
        names = (prop_names,)
    else:
        names = tuple(prop_names or ())

    for prop_name in names:
        if not prop_name:
            continue
        scene_key = sync_idprop_map.get(str(prop_name))
        if scene_key is None:
            continue
        yield str(prop_name), scene_key


def clear_status_notices(
    scene,
    *,
    status_notice_clear_skip_key,
    status_notice_keys,
    recoverable_exceptions,
    logger,
):
    if scene is None:
        return
    try:
        skip_count = int(scene.get(status_notice_clear_skip_key, 0) or 0)
    except recoverable_exceptions:
        skip_count = 0
    except (RuntimeError, TypeError, ValueError, AttributeError):
        skip_count = 0
    if skip_count > 0:
        try:
            scene[status_notice_clear_skip_key] = max(0, int(skip_count) - 1)
        except recoverable_exceptions:
            pass
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
        return
    for key in status_notice_keys:
        try:
            if key in scene:
                del scene[key]
        except recoverable_exceptions:
            logger.debug("Planetka: failed clearing status notice key %s", key, exc_info=True)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            logger.debug("Planetka: failed clearing status notice key %s", key, exc_info=True)


def sync_idprops_from_props(
    scene,
    props,
    *,
    sync_idprop_map,
    recoverable_exceptions,
    logger,
    prop_names=None,
):
    if scene is None or props is None:
        return
    for prop_name, scene_key in _iter_sync_idprop_pairs(sync_idprop_map, prop_names):
        if not hasattr(props, prop_name):
            continue
        try:
            scene[scene_key] = _coerce_storage_value(getattr(props, prop_name))
        except recoverable_exceptions:
            logger.debug("Planetka: failed syncing idprop %s", scene_key, exc_info=True)


def sync_navigation_idprops_from_props(
    scene,
    props,
    *,
    navigation_sync_idprop_map,
    recoverable_exceptions,
    logger,
):
    if scene is None or props is None:
        return
    for prop_name, scene_key in navigation_sync_idprop_map:
        if not hasattr(props, prop_name):
            continue
        try:
            scene[scene_key] = _coerce_storage_value(getattr(props, prop_name))
        except recoverable_exceptions:
            logger.debug("Planetka: failed syncing navigation idprop %s", scene_key, exc_info=True)


def sync_props_from_idprops(
    scene,
    props,
    *,
    sync_idprop_map,
    recoverable_exceptions,
    logger,
):
    if scene is None or props is None:
        return
    for prop_name, scene_key in sync_idprop_map.items():
        if scene_key not in scene or not hasattr(props, prop_name):
            continue
        value = scene.get(scene_key)
        try:
            current = getattr(props, prop_name)
            if isinstance(current, (list, tuple)) and isinstance(value, (list, tuple)):
                setattr(props, prop_name, tuple(value))
            else:
                setattr(props, prop_name, value)
        except recoverable_exceptions:
            logger.debug("Planetka: failed restoring prop %s", prop_name, exc_info=True)

from .error_utils import PLANETKA_RECOVERABLE_EXCEPTIONS


SCENE_SCHEMA_KEY = "planetka_scene_version"
SCENE_SCHEMA_VERSION = 1


def get_scene_schema_version(scene):
    if not scene:
        return 0
    try:
        return int(scene.get(SCENE_SCHEMA_KEY, 0))
    except PLANETKA_RECOVERABLE_EXCEPTIONS:
        return 0


def migrate_scene_schema(scene, sync_idprops_fn, logger=None):
    if not scene:
        return 0

    version = get_scene_schema_version(scene)
    if version >= SCENE_SCHEMA_VERSION:
        return version

    sync_idprops_fn(scene)
    scene[SCENE_SCHEMA_KEY] = SCENE_SCHEMA_VERSION
    return SCENE_SCHEMA_VERSION

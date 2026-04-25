"""Shared explicit exception tuples for internal Planetka tooling.

Blender background invocations do not always place the ``tools/`` directory on
``sys.path`` consistently, so keep this shim at repo root for scripts that
import ``tool_error_utils`` directly.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import zipfile


TOOL_OPTIONAL_IMPORT_EXCEPTIONS = (
    ImportError,
    ModuleNotFoundError,
    OSError,
)


TOOL_RECOVERABLE_EXCEPTIONS = (
    AssertionError,
    AttributeError,
    ConnectionError,
    EOFError,
    ImportError,
    IndexError,
    KeyError,
    LookupError,
    ModuleNotFoundError,
    OSError,
    ReferenceError,
    RuntimeError,
    SyntaxError,
    TimeoutError,
    TypeError,
    UnicodeError,
    ValueError,
    re.error,
    sqlite3.Error,
    subprocess.SubprocessError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
)

"""Shared explicit exception tuples for internal Planetka tooling.

These tools need to keep running through ordinary operational failures
(missing files, import issues, subprocess failures, malformed local data),
but they should not swallow control-flow/system exceptions such as
KeyboardInterrupt or SystemExit.
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

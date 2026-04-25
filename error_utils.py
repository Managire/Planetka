PLANETKA_RECOVERABLE_EXCEPTIONS = (
    AttributeError,
    KeyError,
    LookupError,
    RuntimeError,
    TypeError,
    ValueError,
    OSError,
    ReferenceError,
)

PLANETKA_IMPORT_RECOVERABLE_EXCEPTIONS = (ImportError,) + PLANETKA_RECOVERABLE_EXCEPTIONS


def with_error_code(code, message):
    if code:
        return f"[{code}] {message}"
    return message

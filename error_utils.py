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


def with_error_code(code, message):
    if code:
        return f"[{code}] {message}"
    return message

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Annotated,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

TypedDictType = type[TypedDict]


def _extract_reducer(annotation: Any) -> Callable[[Any, Any], Any] | None:
    if get_origin(annotation) is Annotated:
        _, *metadata = get_args(annotation)
        for item in metadata:
            if callable(item):
                return item
    return None


def _collect_typed_dict_hints(state_type: TypedDictType) -> dict[str, Any]:
    hints: dict[str, Any] = {}
    for cls in reversed(state_type.__mro__):
        if cls in (dict, object) or not hasattr(cls, "__annotations__"):
            continue
        hints.update(get_type_hints(cls, include_extras=True))
    return hints


def merge_state(a: dict, b: dict, state_type: TypedDictType) -> dict:
    if b is None:
        return a
    hints = _collect_typed_dict_hints(state_type)
    result: dict = {}
    all_keys = set(a) | set(b)

    for key in all_keys:
        if key in hints:
            reducer = _extract_reducer(hints[key])
            has_a = key in a
            has_b = key in b
            if reducer and has_a and has_b:
                result[key] = reducer(a[key], b[key])
            elif has_b:
                result[key] = b[key]
            else:
                result[key] = a[key]
        else:
            result[key] = b[key] if key in b else a[key]

    return result

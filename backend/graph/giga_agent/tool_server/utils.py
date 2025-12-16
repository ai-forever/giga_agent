from copy import deepcopy
from typing import Any


def _simplify_nullable_any_type(schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """If schema has anyOf with exactly {T, null},
    remove anyOf and keep non-null branch.

    Returns a tuple of (new_schema, was_anyof_removed).
    """
    any_of = schema.get("anyOf")
    if not isinstance(any_of, list) or len(any_of) != 2:
        return schema, False

    types: list[Any] = []
    for option in any_of:
        if isinstance(option, dict):
            types.append(option.get("type"))
        else:
            types.append(None)

    # Expect exactly one concrete type (string) and one 'null'
    if "null" not in types:
        return schema, False
    non_null_types = [t for t in types if t != "null"]
    if len(non_null_types) != 1 or not isinstance(non_null_types[0], str):
        return schema, False

    non_null_type = non_null_types[0]

    # merge non-null option into the parent, drop anyOf entirely
    non_null_schema = next(
        opt
        for opt in any_of
        if isinstance(opt, dict) and opt.get("type") == non_null_type
    )
    merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "anyOf"}
    for k, v in non_null_schema.items():
        merged[k] = v

    # If original schema (and merged) have no default,
    # set it to null for nullable fields
    if "default" not in merged:
        merged["default"] = None
    return merged, True


def _transform_object(schema_obj: dict[str, Any]) -> dict[str, Any]:
    """Transform an object schema: simplify properties, rebuild required if missing.

    - Removes anyOf when it is exactly {T|null}, keeps other anyOf intact
    - If required is missing, creates it with only properties that
    originally had no anyOf
    """
    new_obj = deepcopy(schema_obj)

    properties = new_obj.get("properties")
    if isinstance(properties, dict):
        required_exists = isinstance(new_obj.get("required"), list)
        required_props = []  # only properties that originally had no anyOf

        for prop_name, prop_schema in properties.items():
            original_prop_schema = prop_schema if isinstance(prop_schema, dict) else {}
            had_anyof_originally = isinstance(original_prop_schema.get("anyOf"), list)

            # Recurse first
            transformed_prop = transform_schema(original_prop_schema)

            # Then try to simplify T|null anyOf at this level
            simplified_prop, removed_anyof = _simplify_nullable_any_type(
                transformed_prop,
            )
            properties[prop_name] = simplified_prop

            if not had_anyof_originally:
                required_props.append(prop_name)

        # If required is missing, set it to properties that had no anyOf originally
        if not required_exists:
            new_obj["required"] = required_props

    # Recurse typical containers even if not an object with properties
    if isinstance(new_obj.get("items"), dict):
        new_obj["items"] = transform_schema(new_obj["items"])

    return new_obj


def transform_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively transform a JSON-like schema according to the rules."""
    if not isinstance(schema, dict):
        return schema

    # If this node looks like an object with properties
    if isinstance(schema.get("properties"), dict):
        return _transform_object(schema)

    # Otherwise, recurse into known containers and try local simplification
    new_schema = deepcopy(schema)

    # Recurse into nested places
    for key in ("items", "additionalProperties"):
        if isinstance(new_schema.get(key), dict):
            new_schema[key] = transform_schema(new_schema[key])

    # Try local simplification for nullable {T|null}
    new_schema, _ = _simplify_nullable_any_type(new_schema)
    return new_schema


def transform_tool(tool: dict[str, Any]) -> dict[str, Any]:
    tool = deepcopy(tool)
    tool["parameters"] = transform_schema(tool["parameters"])
    return tool

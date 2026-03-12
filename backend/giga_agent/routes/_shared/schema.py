from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def build_settings_schema_with_computed_defaults(
    schema_model: type[BaseModel],
) -> dict[str, Any]:
    schema = schema_model.model_json_schema()
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema
    model_fields = getattr(schema_model, "model_fields", None)
    if not isinstance(model_fields, dict):
        return schema

    for field_name, field_info in model_fields.items():
        property_schema = properties.get(field_name)
        if not isinstance(property_schema, dict):
            continue
        if "default" in property_schema or field_info.default_factory is None:
            continue

        try:
            computed_default = field_info.get_default(call_default_factory=True)
        except Exception:
            logger.warning(
                "Failed to compute settings schema default from default_factory",
                extra={
                    "schema_model": schema_model.__name__,
                    "field_name": field_name,
                },
                exc_info=True,
            )
            continue

        if computed_default is None:
            continue

        try:
            json.dumps(computed_default)
        except (TypeError, ValueError):
            logger.debug(
                "Skipping non-JSON-serializable settings schema default",
                extra={
                    "schema_model": schema_model.__name__,
                    "field_name": field_name,
                    "default_type": type(computed_default).__name__,
                },
            )
            continue

        property_schema["default"] = computed_default

    return schema

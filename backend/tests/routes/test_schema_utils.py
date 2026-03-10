import unittest

from pydantic import BaseModel, Field

from giga_agent.routes._shared.schema import (
    build_settings_schema_with_computed_defaults,
)


class SchemaUtilsTests(unittest.TestCase):
    def test_literal_default_is_preserved(self):
        class _Schema(BaseModel):
            foo: int = Field(default=7)

        schema = build_settings_schema_with_computed_defaults(_Schema)

        self.assertEqual(schema["properties"]["foo"]["default"], 7)

    def test_default_factory_is_materialized_into_schema_default(self):
        class _Schema(BaseModel):
            foo: int = Field(default_factory=lambda: 11)

        schema = build_settings_schema_with_computed_defaults(_Schema)

        self.assertEqual(schema["properties"]["foo"]["default"], 11)

    def test_none_default_factory_is_skipped(self):
        class _Schema(BaseModel):
            foo: int | None = Field(default_factory=lambda: None)

        schema = build_settings_schema_with_computed_defaults(_Schema)

        self.assertNotIn("default", schema["properties"]["foo"])

    def test_non_json_serializable_default_factory_is_skipped(self):
        class _Schema(BaseModel):
            foo: set[int] = Field(default_factory=lambda: {1, 2, 3})

        schema = build_settings_schema_with_computed_defaults(_Schema)

        self.assertNotIn("default", schema["properties"]["foo"])

    def test_default_factory_error_does_not_break_schema(self):
        def _boom():
            raise RuntimeError("boom")

        class _Schema(BaseModel):
            foo: int = Field(default_factory=_boom)

        schema = build_settings_schema_with_computed_defaults(_Schema)

        self.assertIn("foo", schema["properties"])
        self.assertNotIn("default", schema["properties"]["foo"])

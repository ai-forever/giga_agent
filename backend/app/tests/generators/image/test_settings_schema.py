import unittest

from giga_agent.generators.image.fusion_brain import FusionBrainImageGen
from giga_agent.generators.image.gigachat import GigaChatImageGen
from giga_agent.generators.image.openai import OpenAIImageGen


class ImageSettingsSchemaTests(unittest.TestCase):
    def test_openai_settings_schema_excludes_runtime_fields(self):
        schema = OpenAIImageGen.settings_schema()

        self.assertIn("model", schema.model_fields)
        self.assertIn("timeout", schema.model_fields)
        self.assertIn("max_retries", schema.model_fields)

        self.assertNotIn("llm", schema.model_fields)
        self.assertNotIn("parallel_calls", schema.model_fields)

    def test_gigachat_settings_schema_excludes_runtime_fields(self):
        schema = GigaChatImageGen.settings_schema()

        self.assertIn("model", schema.model_fields)
        self.assertIn("timeout", schema.model_fields)
        self.assertIn("max_retries", schema.model_fields)

        self.assertNotIn("llm", schema.model_fields)
        self.assertNotIn("parallel_calls", schema.model_fields)

    def test_fusion_brain_schema_keeps_required_keys(self):
        schema = FusionBrainImageGen.settings_schema()

        self.assertIn("api_key", schema.model_fields)
        self.assertIn("secret_key", schema.model_fields)
        self.assertNotIn("llm", schema.model_fields)
        self.assertNotIn("parallel_calls", schema.model_fields)

    def test_supported_llm_provider_types(self):
        self.assertEqual(OpenAIImageGen.supported_llm_provider_types(), ["openai"])
        self.assertEqual(GigaChatImageGen.supported_llm_provider_types(), ["gigachat"])
        self.assertEqual(FusionBrainImageGen.supported_llm_provider_types(), [])

import os
import types
import unittest
from unittest.mock import AsyncMock, patch

from giga_agent.conf import reset_settings_cache
from giga_agent.modules.scraper.module import ScraperModule
from giga_agent.modules.scraper.tool import (
    _get_tavily_extractor,
    _load_via_tavily_extract,
)


class ScraperModuleTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_settings_cache()

    def test_tavily_mode_requires_tavily_api_key(self):
        user = types.SimpleNamespace(llm_id=None, fast_llm_id=None)
        with patch.dict(os.environ, {"GIGA_AGENT_SCRAPER": "tavily"}, clear=True):
            reset_settings_cache()
            self.assertFalse(ScraperModule._is_enabled(user))

        with patch.dict(
            os.environ,
            {"GIGA_AGENT_SCRAPER": "tavily", "TAVILY_API_KEY": "tvly-test"},
            clear=True,
        ):
            reset_settings_cache()
            self.assertTrue(ScraperModule._is_enabled(user))

    async def test_tavily_extractor_is_configured_from_env(self):
        with (
            patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}, clear=True),
            patch("giga_agent.modules.scraper.tool.TavilyExtract") as tavily_extract,
        ):
            _get_tavily_extractor()

        tavily_extract.assert_called_once_with(
            tavily_api_key="tvly-test",
            extract_depth="advanced",
            include_images=True,
            format="markdown",
        )

    async def test_tavily_result_is_normalized_to_scraper_payload(self):
        extractor = types.SimpleNamespace(
            ainvoke=AsyncMock(
                return_value={
                    "results": [
                        {
                            "url": "https://example.com",
                            "raw_content": "# Extracted page",
                            "images": ["https://example.com/image.png"],
                            "favicon": "https://example.com/favicon.ico",
                        }
                    ]
                }
            )
        )

        result = await _load_via_tavily_extract(
            extractor=extractor,
            url="https://example.com",
        )

        extractor.ainvoke.assert_awaited_once_with({"urls": ["https://example.com"]})
        self.assertEqual(
            result,
            {
                "url": "https://example.com",
                "markdown": "# Extracted page",
                "images": ["https://example.com/image.png"],
                "favicon": "https://example.com/favicon.ico",
            },
        )

    async def test_tavily_result_without_content_is_rejected(self):
        extractor = types.SimpleNamespace(
            ainvoke=AsyncMock(return_value={"results": [], "failed_results": []})
        )

        with self.assertRaisesRegex(ValueError, "не вернул содержимое"):
            await _load_via_tavily_extract(
                extractor=extractor,
                url="https://example.com",
            )

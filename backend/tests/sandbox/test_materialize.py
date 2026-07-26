import unittest

from giga_agent.sandbox.base import ContentResult, RedirectResult, StreamResult
from giga_agent.sandbox.materialize import materialize_bounded, metadata_size


async def _gen(chunks):
    for chunk in chunks:
        yield chunk


class MaterializeBoundedTests(unittest.IsolatedAsyncioTestCase):
    async def test_content_within_limit(self):
        data, too_large = await materialize_bounded(ContentResult(data=b"abc"), 10)
        self.assertEqual(data, b"abc")
        self.assertFalse(too_large)

    async def test_content_over_limit(self):
        data, too_large = await materialize_bounded(ContentResult(data=b"a" * 20), 10)
        self.assertIsNone(data)
        self.assertTrue(too_large)

    async def test_stream_early_abort(self):
        result = StreamResult(stream=_gen([b"x" * 6, b"y" * 6]))
        data, too_large = await materialize_bounded(result, 10)
        self.assertIsNone(data)
        self.assertTrue(too_large)

    async def test_stream_within_limit(self):
        result = StreamResult(stream=_gen([b"x" * 3, b"y" * 3]))
        data, too_large = await materialize_bounded(result, 10)
        self.assertEqual(data, b"xxxyyy")
        self.assertFalse(too_large)

    async def test_stream_content_length_rejected_before_reading(self):
        # content_length больше лимита -> сразу too_large, поток не читаем
        consumed = []

        async def _tracking():
            consumed.append(True)
            yield b"z"

        result = StreamResult(stream=_tracking(), content_length=999)
        data, too_large = await materialize_bounded(result, 10)
        self.assertIsNone(data)
        self.assertTrue(too_large)
        self.assertEqual(consumed, [])

    async def test_metadata_size(self):
        self.assertEqual(metadata_size(ContentResult(data=b"abcd")), 4)
        self.assertEqual(
            metadata_size(StreamResult(stream=_gen([]), content_length=42)), 42
        )
        self.assertIsNone(metadata_size(RedirectResult(url="https://x")))
        self.assertEqual(metadata_size(RedirectResult(url="https://x"), 7), 7)


if __name__ == "__main__":
    unittest.main()

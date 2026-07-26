import unittest

from giga_agent.sandbox.manager.file_policy import (
    FileTooLargeError,
    enforce_upload_limit,
)


class FilePolicyTests(unittest.TestCase):
    def test_within_limit_passes(self):
        enforce_upload_limit(declared_size=10, limit=100)  # no raise

    def test_at_limit_passes(self):
        enforce_upload_limit(declared_size=100, limit=100)  # no raise

    def test_over_limit_raises(self):
        with self.assertRaises(FileTooLargeError) as ctx:
            enforce_upload_limit(declared_size=101, limit=100)
        self.assertEqual(ctx.exception.declared_size, 101)
        self.assertEqual(ctx.exception.limit, 100)

    def test_unknown_size_passes(self):
        # None размер (клиент не сообщил) -> проверка по метаданным невозможна
        enforce_upload_limit(declared_size=None, limit=100)  # no raise


if __name__ == "__main__":
    unittest.main()

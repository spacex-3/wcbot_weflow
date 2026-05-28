import os
import tempfile
import unittest

from utils.file_cleanup import cleanup_old_files


class FileCleanupTest(unittest.TestCase):
    def test_cleanup_old_files_removes_only_expired_matching_extensions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_png = os.path.join(tmpdir, "old.png")
            new_png = os.path.join(tmpdir, "new.png")
            old_txt = os.path.join(tmpdir, "old.txt")
            for path in (old_png, new_png, old_txt):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("data")

            now = 1_700_000_000
            eight_days_ago = now - 8 * 24 * 60 * 60
            one_day_ago = now - 24 * 60 * 60
            os.utime(old_png, (eight_days_ago, eight_days_ago))
            os.utime(new_png, (one_day_ago, one_day_ago))
            os.utime(old_txt, (eight_days_ago, eight_days_ago))

            result = cleanup_old_files(
                tmpdir,
                retention_days=7,
                allowed_extensions={".png"},
                now=now,
            )

            self.assertEqual(result["removed"], 1)
            self.assertFalse(os.path.exists(old_png))
            self.assertTrue(os.path.exists(new_png))
            self.assertTrue(os.path.exists(old_txt))


if __name__ == "__main__":
    unittest.main()

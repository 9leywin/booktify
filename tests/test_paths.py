import os
import shutil
import unittest

from bt.paths import is_writable_dir, safe_output_path
from tests.test_importers import work_dir


class PathsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"paths_{self.id().rsplit('.', 1)[-1]}")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_writable_target_is_kept(self) -> None:
        target = os.path.join(self.dir, "out.epub")
        path, moved = safe_output_path(target, os.path.join(self.dir, "fallback"))
        self.assertEqual(path, os.path.abspath(target))
        self.assertFalse(moved)

    def test_blocked_parent_falls_back(self) -> None:
        blocked = os.path.join(self.dir, "blocked")
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("это файл, а не папка")

        target = os.path.join(blocked, "book (RU).epub")
        fallback = os.path.join(self.dir, "books")
        path, moved = safe_output_path(target, fallback)

        self.assertTrue(moved)
        self.assertEqual(os.path.dirname(path), fallback)
        self.assertEqual(os.path.basename(path), "book (RU).epub")
        self.assertTrue(is_writable_dir(fallback))

    def test_probe_does_not_leave_files(self) -> None:
        is_writable_dir(self.dir)
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".bt-")], [])


if __name__ == "__main__":
    unittest.main()

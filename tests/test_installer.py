import os
import shutil
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import installer_main  # noqa: E402
from tests.test_importers import work_dir  # noqa: E402

PAYLOAD = os.path.join(ROOT, "dist-next", "Booktify")


@unittest.skipUnless(os.path.isdir(PAYLOAD), "нет собранного приложения dist-next/Booktify")
class UpdateInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target = work_dir(f"inst_{self.id().rsplit('.', 1)[-1]}")
        os.environ["BT_PAYLOAD"] = PAYLOAD

    def tearDown(self) -> None:
        os.environ.pop("BT_PAYLOAD", None)
        shutil.rmtree(self.target, ignore_errors=True)

    def test_install_and_update_removes_stale_files(self) -> None:
        installer_main.install(self.target, desktop_shortcut=False)
        self.assertTrue(os.path.exists(os.path.join(self.target, "Booktify.exe")))

        stale = os.path.join(self.target, "_internal", "stale_module.py")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write("# старая версия")

        installer_main.install(self.target, desktop_shortcut=False)
        self.assertFalse(os.path.exists(stale), "старые файлы должны удаляться")
        self.assertTrue(os.path.exists(os.path.join(self.target, "Booktify.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.target, "uninstall.ps1")))

    def test_install_is_idempotent(self) -> None:
        installer_main.install(self.target, desktop_shortcut=False)
        first = set(os.listdir(os.path.join(self.target, "_internal")))
        installer_main.install(self.target, desktop_shortcut=False)
        second = set(os.listdir(os.path.join(self.target, "_internal")))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

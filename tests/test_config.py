import os
import shutil
import unittest

from bt import config
from bt.config import Settings
from tests.test_importers import work_dir


class ConfigDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = work_dir(f"cfg_{self.id().rsplit('.', 1)[-1]}")
        self._env = {k: os.environ.get(k) for k in ("BT_CONFIG_DIR", "LOCALAPPDATA", "APPDATA")}
        config.reset_cache()

    def tearDown(self) -> None:
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_uses_env_override(self) -> None:
        os.environ["BT_CONFIG_DIR"] = self.dir
        self.assertEqual(config.config_dir(), self.dir)

    def test_falls_back_when_first_choice_is_not_a_directory(self) -> None:
        blocked = os.path.join(self.dir, "blocked")
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("это файл, а не папка")

        os.environ["BT_CONFIG_DIR"] = blocked
        os.environ["APPDATA"] = os.path.join(self.dir, "appdata-denied")
        os.environ["LOCALAPPDATA"] = os.path.join(self.dir, "local")

        chosen = config.config_dir()
        self.assertNotEqual(chosen, blocked)
        self.assertTrue(os.path.isdir(chosen))
        self.assertTrue(chosen.startswith(self.dir))

    def test_profile_is_used_when_appdata_is_blocked(self) -> None:
        blocked = os.path.join(self.dir, "blocked")
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("файл")
        os.environ["BT_CONFIG_DIR"] = blocked
        os.environ["APPDATA"] = blocked
        os.environ["LOCALAPPDATA"] = blocked
        os.environ["USERPROFILE"] = self.dir

        chosen = config.config_dir()
        self.assertEqual(chosen, os.path.join(self.dir, "Booktify"))

    def test_legacy_data_is_migrated(self) -> None:
        legacy = os.path.join(self.dir, "legacy")
        dest = os.path.join(self.dir, "new")
        os.makedirs(os.path.join(legacy, "cache"), exist_ok=True)
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(legacy, "settings.json"), "w", encoding="utf-8") as fh:
            fh.write('{"quality": "fast"}')
        with open(os.path.join(legacy, "cache", "abc.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")

        self.assertTrue(config.migrate_legacy(legacy, dest))
        self.assertTrue(os.path.exists(os.path.join(dest, "settings.json")))
        self.assertTrue(os.path.exists(os.path.join(dest, "cache", "abc.json")))

    def test_migration_is_noop_for_same_dir(self) -> None:
        self.assertFalse(config.migrate_legacy(self.dir, self.dir))

    def test_existing_settings_win_over_better_folder(self) -> None:
        appdata = os.path.join(self.dir, "roaming")
        local = os.path.join(self.dir, "local")
        os.makedirs(os.path.join(local, "Booktify"), exist_ok=True)
        with open(os.path.join(local, "Booktify", "settings.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")

        os.environ.pop("BT_CONFIG_DIR", None)
        os.environ["APPDATA"] = appdata
        os.environ["LOCALAPPDATA"] = local

        chosen = config.config_dir()
        self.assertEqual(chosen, os.path.join(local, "Booktify"))

    def test_settings_save_and_load(self) -> None:
        os.environ["BT_CONFIG_DIR"] = self.dir
        config.reset_cache()

        settings = Settings(quality="max", jobs=2)
        settings.set_api_key("sk-test-123456")
        settings.save()
        self.assertTrue(os.path.exists(os.path.join(self.dir, "settings.json")))

        restored = Settings.load()
        self.assertEqual(restored.quality, "max")
        self.assertEqual(restored.jobs, 2)
        self.assertEqual(restored.api_key, "sk-test-123456")

    def test_key_is_not_stored_in_plain_text(self) -> None:
        os.environ["BT_CONFIG_DIR"] = self.dir
        config.reset_cache()

        settings = Settings()
        settings.set_api_key("sk-secret-value")
        settings.save()
        with open(os.path.join(self.dir, "settings.json"), encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn("sk-secret-value", raw)


if __name__ == "__main__":
    unittest.main()

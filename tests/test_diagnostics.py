import unittest

from bt.diagnostics import (
    describe_write_problem,
    integrity_level,
    parent_process,
    process_integrity,
    whoami_integrity,
)


class DiagnosticsTest(unittest.TestCase):
    def test_integrity_level_is_known_value(self) -> None:
        self.assertIn(
            integrity_level(),
            {"low", "medium", "high", "system", "untrusted", "unknown"},
        )

    def test_description_mentions_level(self) -> None:
        text = describe_write_problem()
        self.assertTrue("уровень целостности" in text or "низким уровнем" in text)

    def test_parent_process_is_found(self) -> None:
        pid, name = parent_process()
        if pid:
            self.assertIsInstance(name, str)
            self.assertNotEqual(process_integrity(pid), "")

    def test_process_integrity_of_unknown_pid(self) -> None:
        self.assertIn(process_integrity(0), {"unknown", "no-access"})

    def test_whoami_matches_reasonable_value(self) -> None:
        self.assertIn(
            whoami_integrity(),
            {"low", "medium", "high", "system", "unknown"},
        )


if __name__ == "__main__":
    unittest.main()

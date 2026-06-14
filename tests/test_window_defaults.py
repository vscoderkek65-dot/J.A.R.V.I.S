from __future__ import annotations

import unittest

import app_config


class WindowDefaultsTests(unittest.TestCase):
    def test_windowed_mode_is_default(self):
        self.assertEqual(app_config.DEFAULT_CONFIG["window_mode"], "windowed")
        self.assertLessEqual(app_config.DEFAULT_CONFIG["window_width"], 1680)
        self.assertFalse(app_config.DEFAULT_CONFIG["window_always_on_top"])


if __name__ == "__main__":
    unittest.main()

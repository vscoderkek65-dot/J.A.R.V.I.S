from __future__ import annotations

import unittest

from ui import constants
from ui import orb
from ui.panels import PanelsMixin


class UIModuleImportTests(unittest.TestCase):
    def test_orb_layout_dependencies_are_imported(self) -> None:
        self.assertIs(orb.LEFT_W_T, constants.LEFT_W_T)
        self.assertIs(orb.RIGHT_W_T, constants.RIGHT_W_T)
        self.assertIs(orb.INPUT_H, constants.INPUT_H)
        self.assertTrue(callable(orb.load_app_config))
        self.assertIs(orb.tk.END, orb.tk.END)
        self.assertTrue(callable(PanelsMixin._draw_left_panel))
        self.assertTrue(callable(PanelsMixin._draw_right_panel))


if __name__ == "__main__":
    unittest.main()

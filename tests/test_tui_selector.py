import unittest

from bootstrap.tui import ChoiceRow, Key, SelectorState, reduce_selector, set_filter


def fixture() -> SelectorState:
    return SelectorState(
        (
            ChoiceRow("chrome", "Browsers", "Google Chrome", True, installed=True),
            ChoiceRow("chromium", "Browsers", "Chromium", True),
            ChoiceRow("code", "Editors", "Visual Studio Code", False),
            ChoiceRow("nvim", "Editors", "Neovim", False),
        )
    )


class SelectorTests(unittest.TestCase):
    def test_space_on_group_toggles_the_complete_group(self):
        state = reduce_selector(fixture(), Key.SPACE)
        self.assertNotIn("chrome", state.selected_ids())
        self.assertNotIn("chromium", state.selected_ids())

        state = reduce_selector(state, Key.SPACE)
        self.assertIn("chrome", state.selected_ids())
        self.assertIn("chromium", state.selected_ids())

    def test_space_on_item_toggles_only_the_item(self):
        state = reduce_selector(fixture(), Key.DOWN)
        state = reduce_selector(state, Key.SPACE)

        self.assertNotIn("chrome", state.selected_ids())
        self.assertIn("chromium", state.selected_ids())

    def test_filter_searches_collapsed_groups_and_keeps_group_context(self):
        state = reduce_selector(fixture(), Key.LEFT)
        state = set_filter(state, "visual")

        rows = state.visible_rows()
        self.assertEqual(tuple(row.group for row in rows), ("Editors", "Editors"))
        self.assertEqual(rows[1].id, "code")

    def test_all_and_none_apply_to_visible_choices(self):
        state = set_filter(fixture(), "editor")
        state = reduce_selector(state, Key.ALL)
        self.assertEqual(state.selected_ids(), {"chrome", "chromium", "code", "nvim"})

        state = reduce_selector(state, Key.NONE)
        self.assertEqual(state.selected_ids(), {"chrome", "chromium"})

    def test_navigation_wraps(self):
        state = reduce_selector(fixture(), Key.UP)
        self.assertEqual(state.cursor, len(state.visible_rows()) - 1)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

from ethernity.cli import startup


class TestCliStartup(unittest.TestCase):
    def test_run_startup_init_config_exits(self) -> None:
        with mock.patch.object(startup, "_configure_ui") as configure_mock:
            with mock.patch.object(startup, "_ensure_playwright_browsers") as pw_mock:
                with mock.patch.object(startup, "init_user_config", return_value="/tmp/cfg") as init_mock:
                    with mock.patch.object(startup, "user_config_needs_init") as needs_mock:
                        with mock.patch.object(startup.console, "print") as print_mock:
                            result = startup.run_startup(
                                quiet=False,
                                no_color=False,
                                no_animations=False,
                                debug=False,
                                init_config=True,
                            )
        self.assertTrue(result)
        configure_mock.assert_called_once()
        pw_mock.assert_called_once()
        init_mock.assert_called_once()
        needs_mock.assert_not_called()
        print_mock.assert_called_once()

    def test_run_startup_initializes_missing_config(self) -> None:
        with mock.patch.object(startup, "_configure_ui"):
            with mock.patch.object(startup, "_ensure_playwright_browsers"):
                with mock.patch.object(startup, "user_config_needs_init", return_value=True):
                    with mock.patch.object(startup, "init_user_config", return_value="/tmp/cfg") as init_mock:
                        with mock.patch.object(startup.console, "print"):
                            result = startup.run_startup(
                                quiet=True,
                                no_color=True,
                                no_animations=True,
                                debug=False,
                                init_config=False,
                            )
        self.assertFalse(result)
        init_mock.assert_called_once()

    def test_run_startup_no_config_needed(self) -> None:
        with mock.patch.object(startup, "_configure_ui"):
            with mock.patch.object(startup, "_ensure_playwright_browsers"):
                with mock.patch.object(startup, "user_config_needs_init", return_value=False):
                    with mock.patch.object(startup, "init_user_config") as init_mock:
                        result = startup.run_startup(
                            quiet=True,
                            no_color=True,
                            no_animations=True,
                            debug=False,
                            init_config=False,
                        )
        self.assertFalse(result)
        init_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

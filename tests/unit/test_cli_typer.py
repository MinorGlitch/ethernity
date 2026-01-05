import unittest

from typer.testing import CliRunner

from ethernity.cli import app


class TestCliTyper(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_help_includes_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("backup", result.output)
        self.assertIn("recover", result.output)

    def test_version_flag(self) -> None:
        result = self.runner.invoke(app, ["--version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ethernity", result.output.lower())

    def test_manpage_output(self) -> None:
        result = self.runner.invoke(app, ["manpage"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(".TH ETHERNITY", result.output)


if __name__ == "__main__":
    unittest.main()

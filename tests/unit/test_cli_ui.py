import io
import sys
import unittest
from unittest import mock

from ethernity.cli.ui.state import (
    THEME,
    UIContext,
    WizardState,
    create_default_context,
    format_hint,
    get_context,
    isatty,
)
from ethernity.cli.ui.summary import format_auth_status


class TestIsatty(unittest.TestCase):
    """Tests for isatty function."""

    def test_real_stream_tty(self) -> None:
        """Test with a real stream that has isatty method."""
        stream = mock.MagicMock()
        stream.isatty.return_value = True
        result = isatty(stream, fallback=sys.stdout)
        self.assertTrue(result)

    def test_real_stream_not_tty(self) -> None:
        """Test with a real stream that's not a TTY."""
        stream = mock.MagicMock()
        stream.isatty.return_value = False
        result = isatty(stream, fallback=sys.stdout)
        self.assertFalse(result)

    def test_stream_raises_oserror(self) -> None:
        """Test when stream.isatty raises OSError."""
        stream = mock.MagicMock()
        stream.isatty.side_effect = OSError("not available")
        result = isatty(stream, fallback=sys.stdout)
        self.assertFalse(result)

    def test_stream_raises_valueerror(self) -> None:
        """Test when stream.isatty raises ValueError."""
        stream = mock.MagicMock()
        stream.isatty.side_effect = ValueError("closed")
        result = isatty(stream, fallback=sys.stdout)
        self.assertFalse(result)

    def test_none_stream_with_fallback(self) -> None:
        """Test when stream is None, uses fallback."""
        fallback = mock.MagicMock()
        fallback.isatty.return_value = True
        result = isatty(None, fallback=fallback)
        self.assertTrue(result)

    def test_none_stream_fallback_no_isatty(self) -> None:
        """Test when stream is None and fallback has no isatty."""
        fallback = object()  # No isatty method
        result = isatty(None, fallback=fallback)
        self.assertFalse(result)

    def test_stringio_not_tty(self) -> None:
        """Test StringIO is not a TTY."""
        stream = io.StringIO()
        result = isatty(stream, fallback=sys.stdout)
        self.assertFalse(result)


class TestWizardState(unittest.TestCase):
    """Tests for WizardState dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        state = WizardState(name="backup", total_steps=5)
        self.assertEqual(state.name, "backup")
        self.assertEqual(state.total_steps, 5)
        self.assertEqual(state.step, 0)
        self.assertFalse(state.quiet)

    def test_custom_values(self) -> None:
        """Test custom values."""
        state = WizardState(name="recover", total_steps=3, step=2, quiet=True)
        self.assertEqual(state.name, "recover")
        self.assertEqual(state.total_steps, 3)
        self.assertEqual(state.step, 2)
        self.assertTrue(state.quiet)

    def test_step_mutation(self) -> None:
        """Test step can be mutated."""
        state = WizardState(name="test", total_steps=10)
        state.step = 5
        self.assertEqual(state.step, 5)


class TestUIContext(unittest.TestCase):
    """Tests for UIContext dataclass."""

    def test_default_context_state(self) -> None:
        """Test default context state."""
        context = create_default_context()
        self.assertTrue(context.animations_enabled)
        self.assertIsNone(context.wizard_state)

    def test_theme_attached(self) -> None:
        """Test theme is attached to context."""
        context = create_default_context()
        self.assertEqual(context.theme, THEME)

    def test_consoles_created(self) -> None:
        """Test consoles are created."""
        context = create_default_context()
        self.assertIsNotNone(context.console)
        self.assertIsNotNone(context.console_err)


class TestGetContext(unittest.TestCase):
    """Tests for get_context function."""

    def test_returns_default_context(self) -> None:
        """Test returns default context."""
        context = get_context()
        self.assertIsInstance(context, UIContext)

    def test_returns_same_context(self) -> None:
        """Test returns same context instance."""
        context1 = get_context()
        context2 = get_context()
        self.assertIs(context1, context2)


class TestFormatHint(unittest.TestCase):
    """Tests for format_hint function."""

    def test_basic_hint(self) -> None:
        """Test basic hint formatting."""
        hint = format_hint("Press Enter to continue")
        text_str = str(hint)
        self.assertIn("Hint:", text_str)
        self.assertIn("Press Enter to continue", text_str)

    def test_empty_hint(self) -> None:
        """Test empty hint text."""
        hint = format_hint("")
        text_str = str(hint)
        self.assertIn("Hint:", text_str)


class TestFormatAuthStatus(unittest.TestCase):
    """Tests for format_auth_status function."""

    def test_verified_status(self) -> None:
        """Test verified status."""
        result = format_auth_status("verified", allow_unsigned=False)
        self.assertEqual(result, "verified")

    def test_verified_with_allow_unsigned(self) -> None:
        """Test verified status ignores allow_unsigned."""
        result = format_auth_status("verified", allow_unsigned=True)
        self.assertEqual(result, "verified")

    def test_missing_status_strict(self) -> None:
        """Test missing status when unsigned not allowed."""
        result = format_auth_status("missing", allow_unsigned=False)
        self.assertEqual(result, "missing")

    def test_missing_status_with_skip(self) -> None:
        """Test missing status when unsigned allowed."""
        result = format_auth_status("missing", allow_unsigned=True)
        self.assertEqual(result, "skipped (--skip-auth-check)")

    def test_ignored_status(self) -> None:
        """Test ignored status."""
        result = format_auth_status("ignored", allow_unsigned=False)
        self.assertEqual(result, "failed (check skipped)")

    def test_ignored_with_allow_unsigned(self) -> None:
        """Test ignored status with allow_unsigned."""
        result = format_auth_status("ignored", allow_unsigned=True)
        self.assertEqual(result, "failed (check skipped)")

    def test_unknown_status_passthrough(self) -> None:
        """Test unknown status passes through."""
        result = format_auth_status("custom-status", allow_unsigned=False)
        self.assertEqual(result, "custom-status")


class TestTheme(unittest.TestCase):
    """Tests for THEME configuration."""

    def test_theme_has_required_styles(self) -> None:
        """Test theme has all required style keys."""
        required_styles = [
            "title",
            "subtitle",
            "accent",
            "success",
            "warning",
            "error",
            "rule",
            "panel",
            "muted",
        ]
        for style in required_styles:
            self.assertIn(style, THEME.styles)

    def test_theme_styles_are_valid(self) -> None:
        """Test theme styles are non-empty."""
        for name, style in THEME.styles.items():
            self.assertIsNotNone(style, f"Style {name} should not be None")


if __name__ == "__main__":
    unittest.main()

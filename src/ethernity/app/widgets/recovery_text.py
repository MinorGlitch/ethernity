"""Paper transcription aids on Textual's normal text editor."""

from __future__ import annotations

import re

from rich.text import Text
from textual.widgets import TextArea

from ethernity.encoding.fallback_text import detect_fallback_section, split_fallback_line_label
from ethernity.encoding.zbase32 import ZBASE32_ALPHABET


class RecoveryTextArea(TextArea):
    COMPONENT_CLASSES = TextArea.COMPONENT_CLASSES | {
        "recovery--group",
        "recovery--label",
        "recovery--invalid",
    }
    DEFAULT_CSS = """
    RecoveryTextArea .recovery--group { color: $accent; }
    RecoveryTextArea .recovery--label { color: $text-muted; text-style: strike; }
    RecoveryTextArea .recovery--invalid { color: $text-error; text-style: bold underline; }
    """

    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        label, body = split_fallback_line_label(line.plain)
        if label:
            line.stylize(self.get_component_rich_style("recovery--label"), 0, len(label))
        if detect_fallback_section(body):
            return line
        for index, match in enumerate(re.finditer(r"[^\s-]+", body)):
            start, end = len(label) + match.start(), len(label) + match.end()
            if index % 2 == 0:
                line.stylize(self.get_component_rich_style("recovery--group"), start, end)
            for offset, char in enumerate(match[0], start):
                valid = char.isascii() and (
                    char.lower() in ZBASE32_ALPHABET if label else char.isalnum() or char in "+/"
                )
                if not valid:
                    line.stylize(
                        self.get_component_rich_style("recovery--invalid"), offset, offset + 1
                    )
        return line

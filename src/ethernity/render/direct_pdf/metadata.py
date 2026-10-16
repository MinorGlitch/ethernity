"""Printable recovery fields shared by document designs."""

from __future__ import annotations

from dataclasses import dataclass

from ethernity.render.recovery_meta import PASSPHRASE_PRINT_MODE_JSON_PARTS, RecoveryMeta
from ethernity.render.types import RenderTextMetadata


@dataclass(frozen=True)
class RecoveryField:
    label: str
    value_lines: tuple[str, ...]
    guidance: str
    text_metadata: RenderTextMetadata

    @property
    def visible(self) -> bool:
        return bool(self.value_lines)


@dataclass(frozen=True)
class RecoveryFields:
    quorum: RecoveryField
    passphrase: RecoveryField
    signing_key: RecoveryField

    def visible_rows(self) -> tuple[RecoveryField, ...]:
        return tuple(row for row in (self.quorum, self.passphrase, self.signing_key) if row.visible)


def recovery_fields(
    meta: RecoveryMeta,
    *,
    signing_key_label: str = "Master Signing Public Key",
    single_line_passphrase: bool = False,
    raw_passphrase: bool = False,
) -> RecoveryFields:
    """Choose field content once; designs own order, labels, and placement."""

    lines = meta.passphrase_lines
    guidance = meta.passphrase_instructions
    if (
        single_line_passphrase
        and lines
        and meta.passphrase_print_mode != PASSPHRASE_PRINT_MODE_JSON_PARTS
    ):
        lines = (" ".join(lines),)
    if not lines and raw_passphrase and meta.passphrase:
        lines = (meta.passphrase,)
        guidance = ""
    return RecoveryFields(
        quorum=RecoveryField(
            meta.quorum_label,
            (meta.quorum_value,) if meta.quorum_value else (),
            "",
            RenderTextMetadata("recovery_quorum"),
        ),
        passphrase=RecoveryField(
            meta.passphrase_label,
            lines,
            guidance,
            RenderTextMetadata("recovery_passphrase", meta.passphrase_print_mode),
        ),
        signing_key=RecoveryField(
            signing_key_label,
            meta.signing_pub_lines,
            "",
            RenderTextMetadata("recovery_signing_public_key"),
        ),
    )

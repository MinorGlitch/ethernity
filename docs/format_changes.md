# Format Changes

This document tracks format evolution over time.

`docs/format.md` remains the single normative specification. This file is a change ledger and
release-facing summary, not a replacement for normative text.

## Update Policy

For any format-related addition or change:

1. Update `docs/format.md` when wire format, validation behavior, or interoperability requirements
   change.
2. Update `docs/format_notes.md` only for rationale and operational guidance (non-normative).
3. Add an entry here describing the delta and compatibility impact.
4. Add or update tests that cover must-pass and must-reject behavior for the change.

## Entry Template

Use this template for each change entry:

```md
## YYYY-MM-DD - <short change title>

- Type: <wire-format | validation | editorial | notes-only>
- Normative spec updated: <yes/no>
- Sections changed: <for example: 5, 10, 17, 18.3>
- Compatibility:
  - Old decoders reading new artifacts: <yes/no/partial + short note>
  - New decoders reading old artifacts: <yes/no/partial + short note>
- Version/profile bump required: <yes/no + rationale>
- Implementation refs:
  - <path>
- Test refs:
  - <path>
- Security impact:
  - <none or short note>
```

## Versioning Guidance

- Bump version/profile when an older decoder could misinterpret bytes, accept invalid data, or fail
  security-critical validation under the new behavior.
- No bump is typically needed for editorial clarifications, rationale-only notes, or strict fail-
  closed checks that preserve safe rejection semantics.

## Entries

## 2026-03-06 - Format change tracking structure introduced

- Type: editorial
- Normative spec updated: no
- Sections changed: none
- Compatibility:
  - Old decoders reading new artifacts: unchanged
  - New decoders reading old artifacts: unchanged
- Version/profile bump required: no (documentation process only)
- Implementation refs:
  - N/A
- Test refs:
  - N/A
- Security impact:
  - none

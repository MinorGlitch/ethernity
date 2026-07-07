# Terminal CLI Hard Break Release Notes Draft

## Summary

This release replaces the old prompt-driven interactive CLI with a terminal application.
Running `ethernity` now opens the Textual app for human workflows. Scriptable usage lives under
`ethernity run`.

## Breaking Changes

- Old top-level interactive commands are removed.
- The old `ethernity api` command group is removed.
- Typer, Questionary, and direct prompt-toolkit UI code are no longer part of the CLI surface.
- Prompt-loop workspaces, guided wizard modules, and first-run prompt onboarding are removed.

## New Human Surface

Run:

```sh
ethernity
```

The terminal app provides task navigation, editable task sections, right-side preview, on-demand
internals, file pickers, and a final review before any write action.

Primary tasks:

- Create backup
- Restore files
- Add files
- Rebuild backup
- Replace recovery documents
- Recovery kit
- Setup check
- Settings

## New Scriptable Surface

Use `ethernity run` for scripts and automation:

```sh
ethernity run backup --input secrets.txt --output-dir backup-out --yes
ethernity run restore --scan backup-out --output recovered --passphrase "$PASSPHRASE" --yes
ethernity run add-files --backup-folder backup-out --input new-file.txt --passphrase "$PASSPHRASE" --yes
ethernity run rebuild --scan scans --output-dir rebuilt --passphrase "$PASSPHRASE" --yes
ethernity run replace-recovery-docs --scan scans --output-dir replacement-docs --passphrase "$PASSPHRASE" --yes
ethernity run print-kit --output recovery_kit_qr.pdf --yes
ethernity run doctor
```

Machine-readable output is available with `--json` on `ethernity run` commands.

## Safety Model

- No files are written before final review in the Textual app.
- `ethernity run ...` requires `--yes` for write actions.
- Preview output shows planned writes before execution.
- Backup internals are available on demand and redact sensitive values by default.

## Migration Notes

Old command terms map to the new public task language:

| Old surface | New surface |
| --- | --- |
| `recover` | `ethernity run restore` |
| `extend` | `ethernity run add-files` |
| `compact` | `ethernity run rebuild` |
| `mint` | `ethernity run replace-recovery-docs` |
| `kit` | `ethernity run print-kit` |
| `api ...` | `ethernity run ... --json` |

There are no compatibility aliases for the removed commands.

# Advanced workflows

Use this guide after creating and restoring a disposable test backup. The guided app includes each
workflow below; the command examples are for scripts and repeatable operator procedures.

Three rules govern backup updates:

- An update can add or replace files. It cannot delete or rename them.
- An update created from scans needs the original backup and each earlier update during restore.
- Ethernity can assess only the pages and files you load. It cannot find a newer copy elsewhere.

After you create a backup or update, use **Copy fingerprint** on the result screen and store the
full fingerprint with your inventory. Printed pages show a shorter document ID; freshness checks
need the full fingerprint.

## Add or replace files

An update can add new paths or replace matching paths. Paths you do not select remain unchanged.

In the examples below, replace `example passphrase` with the passphrase that protects your backup.

### From an existing backup folder

Preview the update first:

```sh
ethernity run add-files \
  --backup-folder ./backup \
  --input ./docs/new-note.txt \
  --passphrase "example passphrase" \
  --preview
```

Review the planned files and destination. When it is correct, run the same command with `--yes` in
place of `--preview`:

```sh
ethernity run add-files \
  --backup-folder ./backup \
  --input ./docs/new-note.txt \
  --passphrase "example passphrase" \
  --yes
```

Ethernity writes the update alongside the existing backup documents and keeps those documents
unchanged. Save the new full fingerprint before starting another update.

The original backup pages plus the passphrase or enough recovery sheets authorize an update. Sheets
that recover signing authority do not add another approval.

### From printed pages or scans

When printed pages or scans are the source of truth, keep the source and destination separate.
Supply the QR pages for the backup version you trust as latest and enter the full fingerprint you
recorded when you created that version. Replace the angle-bracketed placeholder before running the
command:

```sh
ethernity run add-files \
  --scan ./current-backup-scans \
  --output-folder ./backup-update \
  --input ./docs/new-note.txt \
  --passphrase "example passphrase" \
  --expected-head "<fingerprint from the latest trusted page>" \
  --unlock-policy reuse-root \
  --recovery-count 0 \
  --yes
```

The example explicitly reuses the original passphrase shard set and creates no extension-specific
passphrase shards. A self-contained update always creates its own passphrase shards; a zero recovery
count is valid only with `--unlock-policy reuse-root`.

If you cannot confirm that the scans contain the latest version, stop and find the latest pages.
`--allow-stale-head` is an explicit acknowledgement of that risk; it is not a way to discover a
newer version elsewhere.

An update created from scans is not a standalone backup. Keep the original backup pages, every
previous update, and the new update together. Use [rebuild](#rebuild-a-standalone-backup) when you
need one fresh standalone set.

## Repair an interrupted publication

The `.chain.lock` file is permanent and normally requires no maintenance. If Add Files was
interrupted and a later operation reports an unfinished transaction, inspect it without changing
anything:

```sh
ethernity run doctor \
  --backup-folder ./backup \
  --passphrase "example passphrase"
```

After reviewing the authenticated head and transaction status, apply the supported repair:

```sh
ethernity run doctor \
  --backup-folder ./backup \
  --passphrase "example passphrase" \
  --repair \
  --yes
```

Doctor inspects snapshot-matching transactions whose root, expected parent, index, new document
hash, signed extension, and decrypted ancestry match the authenticated chain. Repair can remove a
duplicate staging directory after confirming that its final directory is already in the
authenticated committed chain, and it can replace the obsolete directory form of `.chain.lock`.
It refuses to resume journaled staging because transaction version 1 does not authenticate the
original optional-carrier policy. Repair instead moves authenticated, snapshot-matching journaled
staging to a hidden sibling quarantine, preserving it while freeing the backup's extension
namespace for a fresh Add Files operation. It refuses to remove unjournaled staging whose ownership
is unknown. Inside a canonical backup, do not delete `.chain.lock`, `.transaction.json`, or
`.staging-*` paths manually.

Scan-mode output is different: its output folder must be a dedicated missing or empty folder and
Doctor does not operate on it. If Add Files was interrupted before an `extension-*` directory was
published, confirm that no Add Files process is still running, then abandon the entire output
folder or select a new empty one. Do not delete its hidden entries individually. If the folder
contains a published `extension-*` directory, preserve that completed bundle.

## Restore the latest state

Give restore all the pages needed to reconstruct the version you want. Ethernity can only select the
newest valid version among the material supplied to that operation; it cannot check another drawer,
computer, or offline copy for a newer version.

If you have mixed versions, use the full fingerprint you recorded for the version you trust as
latest. A file name or scan time cannot prove which backup version is newest.

If two updates start from the same version, Ethernity cannot merge them. There is no online ledger;
the newest version means the newest valid version among the material supplied to that operation.

## Rebuild a standalone backup

Rebuild turns the supplied backup history into a fresh standalone set and leaves the source folder
untouched:

```sh
ethernity run rebuild \
  --backup-folder ./backup \
  --output-dir ./backup-rebuilt \
  --passphrase "example passphrase" \
  --yes
```

Rebuild does not add or remove backed-up files. It keeps the source passphrase and signing key while
creating new recovery sheets. It does not rotate credentials, revoke older authority, or replace the
source set automatically.

Create a new backup instead when you need a new passphrase or signing key, need to remove or rename
paths, or are responding to a compromise. Restore the files you want, create the new backup, verify
restoration, and retire the superseded pages and digital copies.

## Replace recovery sheets

Use the **Create replacement recovery sheets** workflow when the backed-up files should stay the same
but a recovery sheet set needs to be replaced. Print and verify the new sheets before retiring the old
ones. Old sheets remain sensitive until they are destroyed or secured.

The workflow can replace passphrase recovery sheets, signing-key recovery sheets, or both. The
signing-key sheets recover signing authority; they are not a second approval step.

## Create an unanchored offline browser rescue tool

This expert operation creates an **unanchored rescue kit** containing offline restore tools. It is
not chain-bound, cannot authenticate which supplied extension is the expected latest state, and does
not replace backup pages, recovery sheets, or the replacement kit generated by Add Files.

```sh
ethernity run print-kit --output ./recovery-kit.pdf --yes
```

The default rescue kit is smaller and supports manual QR entry. The guided app can create the
scanner variant when camera input is useful. Print the PDF at its selected paper size and test it
with a disposable backup before relying on it.

## Related reference

- [Format specification](format.md)
- [Extension operations and publication profile](extension_publication_profile.md)
- [Format notes](format_notes.md)
- [Security policy](../SECURITY.md)

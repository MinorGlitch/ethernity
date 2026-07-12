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
  --recovery-count 0 \
  --yes
```

The example explicitly creates no new recovery sheets, so the passphrase is included in the update
recovery document. Use that only when the storage plan accepts the risk. Otherwise, load sufficient
recovery material and choose the recovery settings appropriate for the people and places holding it.

If you cannot confirm that the scans contain the latest version, stop and find the latest pages.
`--allow-stale-head` is an explicit acknowledgement of that risk; it is not a way to discover a
newer version elsewhere.

An update created from scans is not a standalone backup. Keep the original backup pages, every
previous update, and the new update together. Use [rebuild](#rebuild-a-standalone-backup) when you
need one fresh standalone set.

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

## Create the offline browser recovery tool

The recovery kit is a printable PDF containing offline restore tools. It is not a backup and does
not replace backup pages or recovery sheets.

```sh
ethernity run print-kit --output ./recovery-kit.pdf --yes
```

The default kit is smaller and supports manual QR entry. The guided app can create the scanner
variant when camera input is useful. Print the PDF at its selected paper size and test it with a
disposable backup before relying on it.

## Related reference

- [Format specification](format.md)
- [Format notes](format_notes.md)
- [Security policy](../SECURITY.md)

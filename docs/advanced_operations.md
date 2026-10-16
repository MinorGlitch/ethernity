# Advanced operations

Use this guide to update a backup, restore a chosen version, rebuild it, replace recovery sheets,
or print the browser recovery kit. These operations are available in the terminal app and through
`ethernity run`.

## Choose the documents to load

Start with the original backup and the updates needed for the version you want:

| Update mode | Required backup documents |
| --- | --- |
| Cumulative, the default | Original backup and selected update |
| Incremental | Original backup and every update through the selected version |

Restoring the original alone needs no updates. To unlock a backup, supply its passphrase or enough
recovery sheets. Signing-key sheets recover the signing key; they are not another approval step
for an update.

Use `--scan` for PDFs, images of printed pages, or folders. Repeat it for separate locations.
Filenames and folder layout do not determine the backup's identity. Add Files can use scans
directly; you do not need to restore or rebuild first.

Add Files and Restore also accept transcribed backup text with `--recovery-text`, or saved QR data
with `--payloads-file`. Supply separate authentication data with `--auth-text` or
`--auth-payloads-file` when needed.

### Check the version

After creating a backup, update, or rebuilt backup, save its full fingerprint. In the app, use
**Copy fingerprint** on the result screen. Printed pages show a shorter document ID, which cannot
be used in place of the full 64-character fingerprint.

`--expected-head` checks against that recorded fingerprint. Ethernity cannot discover a newer
version kept elsewhere. For Add Files, Rebuild, or replacement sheets, you can instead use
`--allow-stale-head` to accept that the loaded documents may be out of date.

The examples below use `./backup` for the original and `./update-02` for a cumulative update.
Replace the paths, passphrase, and fingerprint placeholders with your own values. To use recovery
sheets, replace `--passphrase` with one `--recovery-document` option per sheet, or one
`--recovery-payloads-file` per saved sheet payload file.

Each example starts with `--preview`, which writes no files. Check the preview, then rerun the
command with `--yes` in place of `--preview` to execute it.

## Add or replace files

In the app, choose **Manage > Add files**. This example creates the first update:

```sh
ethernity run add-files \
  --scan ./backup \
  --input ./docs/new-note.txt \
  --output-dir ./update-01 \
  --expected-head "<full original backup fingerprint>" \
  --passphrase "your backup passphrase" \
  --preview
```

A selected file replaces the file at the same backup path. New paths are added; omitted paths stay
unchanged. Use `--input-dir` for a folder and `--base-dir` to choose how relative paths are formed.
The preview shows which paths will change.

The result is two PDFs in the new output folder. Omit `--output-dir` to use
`backup-<original-id>-update-<number>` in the current directory. The preview shows the exact name;
an existing folder is never overwritten. Each printed update page identifies the original backup,
update number, and update document ID.

The original documents stay unchanged. For the next update, load both `./backup` and `./update-01`
with separate `--scan` options, use update 1's
full fingerprint, and choose a new output folder. Save each new fingerprint before the next update.

### Choose cumulative or incremental updates

If cumulative update 1 adds recovery codes and update 2 changes a password file, update 2 includes
both changes. Keep update 1 only if you want its older version.

Add `--update-mode incremental` to the first update command to reuse data from earlier updates
and potentially print less. You must then retain every update through the version you want.
Later updates detect the mode automatically. Changing it requires Rebuild or a new backup.

The Advanced settings also offer FastCDC chunk sizes. These apply to the first update and remain
fixed for the series. Use a new or rebuilt backup before choosing different sizes.

### Capacity and file changes

The resulting files, metadata, and encryption overhead must fit a 1 MiB standalone backup after
compression and encryption. If they cannot fit, the update is refused and the existing backup is
unchanged. Split larger file sets into separate backups.

Updates cannot delete or truly rename files. They also cannot create conflicting paths such as
files named `a` and `a/b`. Create a new backup to make those changes. Updates require an unsealed
original; see [sealed and unsealed backups](format_rationale.md#sealed-and-unsealed-backups).

### Create new recovery sheets with an update

Add `--new-recovery-sheets` to create a new passphrase sheet set after the update succeeds. The
default is three sheets, any two needed. Use `--recovery-threshold` and `--recovery-count` to change
those numbers.

The sheets are saved outside the update folder, under
`<output-dir>-recovery-sheets/replacement-recovery-<document-id>`. They unlock the original and any
recoverable version based on it. If sheet creation fails, the update is already saved: run
**Replace recovery sheets** for its new fingerprint instead of repeating Add Files.

## Restore a version

In **Restore files**, load the required documents and choose the version. To restore cumulative
update 2 from the command line:

```sh
ethernity run restore \
  --scan ./backup \
  --scan ./update-02 \
  --expected-head "<full update 2 fingerprint>" \
  --passphrase "your backup passphrase" \
  --output ./restored \
  --preview
```

By default, Restore selects the latest valid version among the supplied documents. Use
`--extension-index 0` for the original, `--extension-index 1` for update 1, or
`--extension-doc-hash "<full update fingerprint>"` to select an update by fingerprint. Use only one
selection option. If you also pass `--expected-head`, it must match the selected version.

Supply the documents required by that version's update mode and choose a new output destination.
Conflicting updates cannot be merged.

## Rebuild a standalone backup

Choose **Manage > Rebuild backup** to put the current files into a new backup that needs no earlier
update documents:

```sh
ethernity run rebuild \
  --scan ./backup \
  --scan ./update-02 \
  --output-dir ./backup-rebuilt \
  --expected-head "<full update 2 fingerprint>" \
  --passphrase "your backup passphrase" \
  --preview
```

Rebuild creates `./backup-rebuilt/backup-<id>/` with a separate backup and fresh recovery sheets.
As with Create backup, the selected destination is always a parent folder, whether it already
exists or needs to be created. Each backup gets its own folder. It keeps the passphrase and sealed
state. Unsealed backups keep their signing key; sealed sources receive a new key because they
have no stored signing seed.

Restore the rebuilt backup with its new sheets before retiring the previous documents. Record its
new full fingerprint; the old sheets and fingerprint belong to the old backup.

Rebuild uses automatic compression. An older backup history may exceed the standalone size limit
while still being recoverable. Restore its files into separate new backups, or replace large files
with smaller ones before rebuilding.

To change credentials, remove or rename files, or recover from compromise, restore the files you
want and use **Create backup**. Choose new credentials if the old ones were compromised. Verify
recovery before retiring the superseded pages and digital copies. Rebuild does not revoke old
credentials.

## Replace recovery sheets

Choose **Manage > Replace sheets** to create sheets without changing the backed-up files:

```sh
ethernity run replace-recovery-docs \
  --scan ./backup \
  --scan ./update-02 \
  --output-dir ./replacement-sheets \
  --expected-head "<full update 2 fingerprint>" \
  --passphrase "your backup passphrase" \
  --preview
```

Choose an output folder that does not already exist, even if an existing folder is empty.
Ethernity creates the folder for the replacement sheets.

By default, this creates a new passphrase set with three sheets, any two needed. Change the numbers
with `--recovery-threshold` and `--recovery-count`. Add `--signing-key-recovery` for signing-key
sheets too, or combine it with `--no-passphrase-recovery` for signing-key sheets only.

New sheets belong to the original backup, even when you loaded an update. They can unlock an intact
earlier version if a later update is lost. Rebuilt backups need their own new sheets.

Print and test the new set before retiring the old one. Do not mix sheets from different sets.
Old sets still work when the credentials have not changed, so keep them secure or destroy them.

For compatible replacements within an existing set, supply enough existing sheets and use
`--passphrase-replacement-count`, or use `--signing-key-replacement-count` with existing signing-key
payloads. See `ethernity run replace-recovery-docs --help` for those inputs. Earlier sets bound to a
particular update still require that document; create a complete new set to obtain coverage of
the original alone.

## Create a reusable offline browser recovery kit

The kit contains recovery software and works across compatible backups. You still need your
backup pages and the passphrase or recovery sheets.

```sh
ethernity run print-kit --output ./recovery-kit.pdf --preview
```

The default kit is smaller and accepts manually entered QR data. Add `--variant scanner` for camera
input, or choose the scanner variant in the app. Follow the generated PDF's instructions to recover
the HTML file and open it in a browser offline.

The first two codes, marked START 01 and START 02, create the assembly page. Copy their complete
text into a plain-text file in that order. Line breaks between them are allowed. Save as `start.html`
and open it in a browser. Paste scans from QR 3 onwards into that page in any order, or import a
text file exported by your scanner. The page ignores identical duplicates and reports missing,
damaged, conflicting, or wrong-kit fragments. It keeps accepted parts when a later scan fails.

Once every part is present, choose **Save recovery kit**. Open the downloaded
`recovery_kit.bundle.html` offline. Unpacking runs in a worker while a loading message remains visible;
on slower computers this may take several seconds. Keep the downloaded file to skip reconstruction
next time. The assembly page uses an external QR reader; the scanner variant's camera becomes
available after the complete kit opens.

`--qr-chunk-size` sets the maximum data characters per QR, including the fragment header. The
automatic default is 1839 when the QR settings allow it. The startup codes have separate capacity
checks. Previously printed kits still use the instructions printed with them.

Enter a separately recorded full fingerprint to check the expected version, or acknowledge that
the kit can only assess the documents you supplied. A sealed backup also needs a separately trusted
signing-key fingerprint to verify its AUTH key. See the
[verification rules](extension_publication_rules.md#restore-and-version-checks) for the distinction
between matching documents and an independently verified backup.

## Recover from an interrupted operation

Add Files and Rebuild prepare output in a private `.staging-*` directory before making the final
folder available. Recovery ignores those staging directories. The operations leave source
documents unchanged and refuse to overwrite an existing destination.

After an interruption, first check whether the operation reported a completed output folder. If
only an abandoned staging directory remains, confirm that no writer is still running, then remove
it or leave it ignored. Rerun with a new destination; interrupted writes cannot be resumed.

## References

- [Design decisions](format_rationale.md)
- [Update and recovery rules](extension_publication_rules.md)
- [Format specification](format.md)
- [Security](../SECURITY.md)

# Advanced operations

Use this guide after creating and restoring a disposable test backup. The guided app includes each
operation below; the command examples are suitable for scripts and repeatable recovery drills.

These rules govern backup updates:

- An update can add or replace files. It cannot delete or rename them.
- Every update needs the original backup and each earlier update during restore.
- The resulting file set must fit a standalone backup so Rebuild remains available.
- Ethernity can assess only the pages and files you load. It cannot find a newer copy elsewhere.

After you create a backup or update, use **Copy fingerprint** on the result screen and store the
full fingerprint with your inventory. Printed pages show a shorter document ID; freshness checks
need the full fingerprint.

## Add or replace files

An update can add new paths or replace matching paths. Paths you do not select remain unchanged.
It cannot create a file path conflict such as files `a` and `a/b`. Create a new backup to make that
change because the old path cannot be removed by an update.

Before writing the update, Add Files uses the same standalone encoder as Rebuild to prepare the
complete resulting file set. Compression, file metadata, encryption overhead, and every standalone
limit count toward the check. The final ciphertext must fit 1 MiB; raw input can be larger when it
compresses enough. If the file set cannot fit, the update is refused and your existing backup stays
unchanged. Use separate backups for content that cannot fit together.

In the examples below, replace `example passphrase` with the passphrase that protects your backup.

Load the backup documents from PDFs, images, folders, QR payloads, or fallback text. Their contents
identify the chain. Names and folder organization are for your convenience; you can rearrange the
documents freely.

### From PDFs or folders

Preview the update first. Supply the full fingerprint of the head you trust with
`--expected-head`:

```sh
ethernity run add-files \
  --scan ./backup \
  --input ./docs/new-note.txt \
  --output-dir ./update-01 \
  --expected-head "<full head fingerprint>" \
  --passphrase "example passphrase" \
  --preview
```

Review the planned files and destination. When it is correct, run the same command with `--yes` in
place of `--preview`:

```sh
ethernity run add-files \
  --scan ./backup \
  --input ./docs/new-note.txt \
  --output-dir ./update-01 \
  --expected-head "<full head fingerprint>" \
  --passphrase "example passphrase" \
  --yes
```

Ethernity writes two update PDFs into the new output folder and leaves the source documents
unchanged. Recovery now requires the original backup and every update through the new head.
For the next update, supply both the original backup and this update, for example with
`--scan ./backup --scan ./update-01`. Save the new full fingerprint before starting another update.
Use Rebuild when carrying the whole update chain becomes inconvenient; it creates a new standalone
backup without changing the source chain.

To create fresh passphrase recovery sheets for the chain in the same run, add
`--new-recovery-sheets`. The default is three sheets with any two needed to restore. Use
`--recovery-threshold` and `--recovery-count` to choose another quorum. Add Files still publishes
only its two update documents; after publication it delegates the sheets to Replace Recovery
Docs. The sheets are saved under
`<output-dir>-recovery-sheets/replacement-recovery-<document-id>`, outside the update output
folder.

These new sheets bind to the original root. They can unlock any intact version
of the same chain, including an older version when this update is lost. Use the recorded
fingerprint to identify the version you expect.

If the update succeeds but sheet creation fails, do not repeat Add Files. The update is already
published. Run Replace Recovery Docs for the new full fingerprint instead.

The Settings screen exposes FastCDC chunk sizes under Advanced. The defaults suit normal use.
Custom values apply only when creating the first update in a chain; that update fixes the three
sizes for every later update. To choose other sizes, rebuild or create a standalone backup first.

The authenticated backup documents plus the passphrase or enough recovery sheets authorize an update.
Signing-key recovery sheets recover the key used to sign updates. They do not add another approval.

### From printed pages or scans

Use `--scan` for images of printed pages just as you would for source PDFs. Supply the original
backup and all updates through the intended head. Add Files authenticates and replays them before
creating an update; no Restore or Rebuild step is needed.

Use `--recovery-text` for explicitly transcribed fallback text or `--payloads-file` for saved QR
payloads. If needed, supply authentication separately with `--auth-text` or `--auth-payloads-file`.

If you cannot confirm that the supplied documents contain the latest version, find the latest
pages or explicitly accept that uncertainty with `--allow-stale-head`. This acknowledgement permits
an update from the latest supplied head. It does not establish that a newer offline copy does not
exist. The same freshness requirement applies to original PDFs, scans, and text.

## Interrupted publication

A `.staging-*` directory is unpublished and ignored during recovery. Ethernity does not journal,
resume, repair, or quarantine interrupted extension writes. After establishing that no Add Files
process is running, remove the abandoned staging directory or leave it ignored, then run Add Files
again with a new destination. A successful publication appears as one complete output folder.
Ethernity refuses to overwrite an existing destination.

## Restore the latest version

Give Restore all the pages needed to reconstruct the version you want. Ethernity can only select the
newest valid version among the documents supplied to that operation; it cannot check another drawer,
computer, or offline copy for a newer version.

If you have mixed versions, use the full fingerprint you recorded for the version you trust as
latest. A file name or scan time cannot prove which backup version is newest.

If two updates start from the same version, Ethernity cannot merge them. There is no online head
registry; the newest version means the newest valid version among the documents you supplied.

## Rebuild a standalone backup

Rebuild turns the supplied backup history into a new standalone backup and leaves the source
documents untouched. The source can be a folder of PDFs or scans supplied with `--scan`:

```sh
ethernity run rebuild \
  --scan ./backup \
  --output-dir ./backup-rebuilt \
  --expected-head "<full head fingerprint>" \
  --passphrase "example passphrase" \
  --yes
```

Rebuild does not add or remove backed-up files. It keeps the source passphrase and sealed state
while creating fresh recovery sheets for the new ciphertext identity. An
unsealed source also keeps its signing key. A sealed source has no signing seed in its manifest;
Rebuild generates a new signing key instead, and its new AUTH identifies that key.
Rebuild uses automatic compression to match the capacity check used before publishing updates.
It does not revoke old credentials or the ability to sign updates. It does not replace the source
backup automatically.

The old root-bound sheets belong to the source root. Before retiring the source documents, restore
the new standalone backup with its new sheets. If you use expected-version checks, record its full
fingerprint separately; the old fingerprint will not match the rebuilt backup.

Earlier oversized chains can still restore within the recovery limits even if their combined
file set cannot fit Rebuild. Restore their files into separate new backups, or replace large contents
with smaller contents until a new update passes the standalone check.

Create a new backup instead when you need intentional credential rotation, need to remove or
rename paths, or are responding to a compromise. Restore the files you want, create the new backup,
verify restoration, and retire the superseded pages and digital copies.

## Replace recovery sheets

Use **Create replacement recovery sheets** when the backed-up files should stay the same but a
recovery sheet set needs to be replaced. Print and verify the new sheets before retiring the old
ones. Replacement checks the selected version but binds every sheet to its original root. A lost
later update does not prevent the sheets from unlocking an intact root or older version. Rebuild
creates a new root, so use its fresh sheets rather than sheets from the old chain.

Old sheets remain sensitive until they are destroyed or secured. A new set identifier prevents
mixing sets; it does not revoke old quorums when the credentials remain unchanged.
Compatible replacement sheets remain in the original root-bound set. If you have an earlier
head-bound sheet set, create a complete new root-bound set rather than compatible replacements;
the old sheets still require the exact document they were bound to.

The operation can replace passphrase recovery sheets, signing-key recovery sheets, or both.
Signing-key sheets recover the key used to sign updates. They do not add another approval step.

## Create a reusable offline browser recovery kit

This operation creates one reusable offline restore tool without a trusted backup identity. You
can use it with any backup. It does not replace backup pages or recovery sheets.

```sh
ethernity run print-kit --output ./recovery-kit.pdf --yes
```

The default kit is smaller and supports manual QR entry. The guided app can create the scanner
variant when camera input is useful. Enter a separately recorded full fingerprint to check an
expected version, or acknowledge that recovery can only select among the supplied documents.

An independently trusted full extension-head fingerprint verifies the root identity, signing key,
and selected version after complete authenticated replay. A trusted standalone-root fingerprint
establishes root identity and, for an unsealed root, signing-key identity. For a sealed root, separately
trust the signing-key fingerprint as well. Without an independently trusted record, the kit checks
only internal consistency. A matching record confirms your recorded version. It cannot
establish whether a later offline update exists.

## References

- [Format specification](format.md)
- [Extension publication rules](extension_publication_rules.md)
- [Format rationale and recovery guidance](format_rationale.md)
- [Security policy](../SECURITY.md)

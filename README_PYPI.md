# Ethernity

Ethernity turns small files you cannot afford to lose into encrypted pages you can print, store in
different locations, and restore without internet access.

It works well for seed phrases, key files, small configuration sets, and recovery packets. Use a
regular backup system for large archives, continuous sync, or unattended jobs.

The encrypted content must fit within **1 MiB** and contain no more than **2,048 file paths**.

## Install

Ethernity requires Python 3.11 or newer. Install the CLI in an isolated environment with `pipx`:

```sh
pipx install ethernity-paper
ethernity --help
```

The package name is `ethernity-paper`; the installed command is `ethernity`. A standard Python
environment also works:

```sh
python -m pip install ethernity-paper
```

The [full installation guide](https://github.com/MinorGlitch/ethernity#install) covers Homebrew,
Windows, and release archives.

## Create and restore a test backup

Open the guided terminal app:

```sh
ethernity
```

1. Choose **Create backup** and select a disposable test file or folder.
2. Keep the recommended recovery method: 3 recovery sheets, any 2 can restore.
3. Review the destination and create the backup.
4. Choose **Restore files**, load the backup folder or scanned pages, and unlock them.
5. Restore into an empty destination and compare the result with the original test data.

### Scriptable test

This macOS and Linux example uses a test-only passphrase:

```sh
printf "ethernity README test\n" > test-file.txt

ethernity run backup \
  --input ./test-file.txt \
  --output-dir ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --yes

ethernity run restore \
  --scan ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --output ./restored.txt \
  --yes

cmp ./test-file.txt ./restored.txt
```

`cmp` produces no output when both files match.

## Store your backup safely

- Keep an independent backup outside Ethernity.
- Put recovery sheets in separate locations and keep them apart from the encrypted backup pages.
- Treat every generated page as sensitive and give recovery sheets the same care as passwords.
- Create and restore backups only on computers you trust.
- Print PDFs at actual size and scan at least one printed QR code before storing the set.
- Test a restore from the pages and recovery sheets you plan to keep.

## Other workflows

The guided app can add or replace files, rebuild a backup as one standalone set, create replacement
recovery sheets, and create a printable copy of the offline browser recovery tool.

Run `ethernity run --help` to see the scriptable tasks, including `doctor` for authenticated
inspection and repair of interrupted publication transactions.

## Learn more

### Using Ethernity

- [Project README](https://github.com/MinorGlitch/ethernity)
- [Advanced workflows](https://github.com/MinorGlitch/ethernity/blob/master/docs/advanced-workflows.md)

### Safety and trust

- [Security policy](https://github.com/MinorGlitch/ethernity/blob/master/SECURITY.md)
- [Release verification](https://github.com/MinorGlitch/ethernity/blob/master/docs/release_artifacts.md)

### Technical reference

- [Format specification](https://github.com/MinorGlitch/ethernity/blob/master/docs/format.md)
- [Format rationale and operations](https://github.com/MinorGlitch/ethernity/blob/master/docs/format_notes.md)
- [Compatibility ledger](https://github.com/MinorGlitch/ethernity/blob/master/docs/format_changes.md)

## Contributing and license

Read the [contribution guide](https://github.com/MinorGlitch/ethernity/blob/master/CONTRIBUTING.md)
before opening a pull request. The project uses the
[GPLv3 or later](https://github.com/MinorGlitch/ethernity/blob/master/LICENSE).

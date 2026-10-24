# Ethernity

Ethernity turns a small file or folder into an encrypted paper backup that you can recover offline.

Use it for seed phrases, private keys, certificates, and small sets of configuration files. Use a
conventional backup system for large archives, continuous sync, or unattended jobs.

A standalone backup is limited to **1 MiB of ciphertext** and **2,048 recovered files**.
Updated backups also have chain-wide limits.

## How much fits on paper?

A recovery phrase or short note usually fits on one QR page. With the default Sentinel design
on A4, a 10 KB file that does not compress takes 3 QR pages, or 19 pages if you print the text
fallback, recovery sheets, and inventory too. Text often compresses well; photos and ZIP files
usually shrink little. The 1 MiB limit is a ceiling, not a recommended amount to print.

See [capacity and page counts](https://github.com/MinorGlitch/ethernity/wiki/Capacity-and-page-counts)
for more examples and how to check your files before printing.

## Installation

Install Ethernity in an isolated environment. With [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install --python 3.13 ethernity-paper
ethernity --version
ethernity
```

uv can install Python for you. If `ethernity` is not found, run `uv tool update-shell` and open
a new terminal. Update with `uv tool upgrade ethernity-paper` and remove it with
`uv tool uninstall ethernity-paper`.

With Python 3.11 or newer and [pipx](https://pipx.pypa.io/stable/installation/), use
`pipx install ethernity-paper`. Update with `pipx upgrade ethernity-paper` and remove it with
`pipx uninstall ethernity-paper`. The package name is `ethernity-paper`; the command is `ethernity`.

The [installation guide](https://github.com/MinorGlitch/ethernity/blob/master/docs/install.md)
covers Homebrew and standalone downloads, which include Python. This README describes version
1.2. If you installed an earlier release, use the README at that release's Git tag.

## Create and restore a test backup

Open the guided terminal app:

```sh
ethernity
```

Use `ethernity --web` to open the same app in a browser. It runs locally, works offline, and uses
the same settings and files as the terminal app. Keep the terminal open and press Ctrl+C there
when finished. Use `ethernity --web --no-open` to print the link without opening a browser.

1. Choose **Create backup** and select a disposable test file or folder.
2. Keep the recommended recovery method: three recovery sheets, any two can restore.
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
  --output ./restored \
  --yes

cmp ./test-file.txt ./restored/test-file.txt
```

`cmp` produces no output when both files match.

## Store your backup safely

- Keep an independent backup outside Ethernity.
- Put recovery sheets in separate locations and keep them apart from the encrypted backup pages.
- Treat every generated page as sensitive and give recovery sheets the same care as passwords.
- Create and restore backups only on computers you trust.
- Print PDFs at actual size and scan at least one printed QR code before storing the set.
- Test a restore from the pages and recovery sheets you plan to keep.

## Other operations

The guided app can add or replace files, rebuild a backup as one standalone backup, create
replacement recovery sheets, and print the offline browser recovery kit.

Run `ethernity run --help` to see the scriptable commands.

## Learn more

### Using Ethernity

- [Project README](https://github.com/MinorGlitch/ethernity)
- [Advanced operations](https://github.com/MinorGlitch/ethernity/blob/master/docs/advanced_operations.md)

### Safety and trust

- [Security policy](https://github.com/MinorGlitch/ethernity/blob/master/SECURITY.md)
- [Release verification](https://github.com/MinorGlitch/ethernity/blob/master/docs/release_files.md)

### Technical reference

- [Format specification](https://github.com/MinorGlitch/ethernity/blob/master/docs/format.md)
- [Extension publication rules](https://github.com/MinorGlitch/ethernity/blob/master/docs/extension_publication_rules.md)
- [Format rationale and recovery guidance](https://github.com/MinorGlitch/ethernity/blob/master/docs/format_rationale.md)
- [Format compatibility history](https://github.com/MinorGlitch/ethernity/blob/master/docs/format_history.md)

## Contributing and license

Read the [contribution guide](https://github.com/MinorGlitch/ethernity/blob/master/CONTRIBUTING.md)
before opening a pull request. The project uses the
[GPLv3 or later](https://github.com/MinorGlitch/ethernity/blob/master/LICENSE).

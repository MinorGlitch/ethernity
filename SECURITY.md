# Security

## Report a vulnerability

Report vulnerabilities privately through this repository's GitHub Security Advisories. Include the
affected version or commit, steps to reproduce the problem, and its impact. Do not include private
keys, passphrases, or real backup contents.

If private reporting is unavailable, ask the maintainers for a private channel through the
repository's contact channels. Keep vulnerability details out of public issues.

We aim to acknowledge reports promptly, but do not promise a response or patch deadline. This
policy does not establish support windows for every historical release or claim independent
security certification. Support for older backup formats is documented in the
[compatibility history](docs/format_history.md).

## What Ethernity protects

Ethernity encrypts file contents with age before writing them to backup pages. Reading those pages
alone does not reveal the files without the passphrase. Backup and recovery work offline.

Recovery sheets use Shamir secret sharing to divide a passphrase or signing seed. Fewer than the
required number of shares do not reveal the shared secret. If the threshold is one, each sheet
holds enough information to recover that secret on its own.

Checksums and hashes detect damaged or incorrectly transcribed data. Ed25519 signatures verify
backup authentication records and recovery sheets against a signing key. Establishing that the
key belongs to the backup you intended to restore requires a trusted reference; agreement among
the supplied documents alone is not proof of their origin. The
[update and recovery rules](docs/extension_publication_rules.md#restore-and-version-checks) define
the checks for each kind of backup.

## Limits and assumptions

Use a computer you trust for creation and recovery. A compromised computer can read files and
passphrases before encryption or after decryption. Ethernity cannot prevent coercion or social
engineering, or make a weak user-chosen passphrase resistant to guessing.

Control access to backup pages and recovery sheets. Know how many sheets are needed and who holds
them. Keep the sheets in separate locations, apart from the backup pages, and prefer generated
passphrases. Keep an independent backup and test recovery from the printed copies you store. Keep
the offline recovery kit separately from the backup documents.

Replacing recovery sheets does not disable old sheets when the credentials stay the same.
Rebuild also keeps the passphrase and, for unsealed backups, the signing key. See
[creating a new backup after compromise](docs/advanced_operations.md#rebuild-a-standalone-backup).

Recovery can check the documents supplied to it. It cannot discover a newer update kept elsewhere.
A separately stored, trusted full fingerprint identifies the version you recorded, but cannot
prove that nobody created a later version. Document identifiers also allow pages from the same
backup to be linked together; Ethernity does not provide anonymity.

## Inputs and checks

This policy covers the terminal app, scriptable commands, browser recovery kit, backup and recovery
formats, and release verification. Imported PDFs, images, text, and QR data are untrusted inputs.
Readers must check authentication, paths, and recovery limits. Wrong passphrases and damaged
encrypted data should produce the same decryption failure message.

The desktop reader parses PDFs and images in separate processes with resource limits. Desktop and
browser recovery check the encryption work factor before decryption and bound the work they accept.
The [design decisions](docs/format_rationale.md#why-recovery-has-limits) describe the limits and
worker behavior.

Release signatures identify the source of a release file. See
[release verification](docs/release_files.md#verification-example) for verification instructions.
The [format specification](docs/format.md) defines the cryptographic and decoding requirements.

# Security policy

## Project status

Ethernity is stable software.

Ethernity creates and restores backups when you run it. Keep independent backups and test recovery
regularly.

## Security model

Ethernity's encrypted backups can be recovered offline. They use:

- age encryption for confidentiality
- checksums and hashes to detect changes to recovered backup data
- optional Shamir secret sharing to split passphrases and signing seeds into recovery shares
- Ed25519 signatures to authenticate recovery shares and backup authentication records

## What Ethernity helps protect against

- Disclosure from possession of encrypted backup pages without the passphrase
- Disclosure from one recovery sheet when more than one sheet is required
- Undetected corruption while scanning or transcribing backup data
- Dependence on an online service to read backups

## What Ethernity does not protect against

- A compromised computer during backup or recovery
- Social engineering or coercion
- Weak passphrases selected by users
- Poor storage of recovery shares, such as keeping all sheets together

## Storage and recovery recommendations

- Generate backups on trusted systems.
- Prefer generated passphrases over manually chosen weak phrases.
- Store recovery sheets in separate physical locations.
- Keep the offline recovery kit separate from the backup documents.
- Test recovery periodically on a trusted computer.

## Security assumptions

This project assumes:

- you secure the computers used for backup and recovery
- you control who can access backup pages and recovery sheets
- you understand how many recovery shares are required and who holds them

Weak computer security or poor storage of recovery sheets can expose your files.

## Reporting a vulnerability

Please do not report security vulnerabilities via public issues.

Preferred process:

1. Open a private GitHub Security Advisory draft for this repository.
2. Include reproduction steps, affected versions or commits, and impact.
3. If private advisories are unavailable, contact maintainers through repository channels and
   request a private reporting channel.

We aim to acknowledge reports promptly but do not guarantee a response time.

## Scope of this policy

This policy covers:

- security-sensitive CLI behavior
- recovery document integrity and authentication
- release file signatures and verification guidance

It does not guarantee:

- support windows for all historical versions
- immediate patch timelines
- formal third-party security certification

## References

- [Format specification](docs/format.md)
- [Format rationale and recovery guidance](docs/format_rationale.md)
- [Release file verification](docs/release_files.md)

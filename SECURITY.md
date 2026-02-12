# Security Policy

## Project Status

Ethernity is experimental software.

Treat it as a tool for controlled backup workflows, not as a fully mature backup platform.
Always keep independent backups and run recovery drills.

## Security Model Summary

Ethernity is designed to support offline-recoverable encrypted backups using:

- age-based encryption for ciphertext confidentiality
- integrity checks on recovered payloads
- optional shard-based secret sharing for recovery key material
- signed auxiliary artifacts for authenticity checks

## What Ethernity Helps Protect Against

- Casual disclosure from physical possession of printed documents
- Single-document compromise when sharding is configured correctly
- Silent corruption in recovery payload transfer paths
- Vendor lock-in risk for backup readability

## What Ethernity Does Not Protect Against

- Compromised endpoint during backup or recovery
- Social engineering/coercion attacks
- Weak passphrases selected by users
- Poor shard custody (for example, storing all shards together)

## Operational Safety Recommendations

- Generate backups on trusted systems.
- Prefer generated passphrases over manually chosen weak phrases.
- Store shard documents in separate physical locations.
- Keep recovery kit media separate from main backup media.
- Validate recovery periodically in a controlled environment.

## Threat Boundaries and Assumptions

This project assumes:

- local host security is your responsibility
- physical document custody practices are enforced by operators
- users understand threshold sharding tradeoffs

If these assumptions do not hold, security outcomes degrade quickly.

## Reporting a Vulnerability

Please do not report security vulnerabilities via public issues.

Preferred process:

1. Open a private GitHub Security Advisory draft for this repository.
2. Include reproduction steps, affected versions/commits, and impact.
3. If private advisory flow is unavailable, contact maintainers through repository channels and request a private path.

We will acknowledge triage as quickly as possible, but no strict SLA is guaranteed.

## Scope of This Policy

This policy covers:

- CLI security-sensitive behavior
- recovery artifact integrity/authentication paths
- release artifact provenance and verification guidance

It does not guarantee:

- support windows for all historical versions
- immediate patch timelines
- formal third-party security certification

## Additional References

- Core format specification: `docs/format.md`
- Non-normative format notes: `docs/format_notes.md`
- Release artifact verification: `docs/release_artifacts.md`

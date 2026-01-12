---
name: Open source readiness checklist
about: Track open-source readiness tasks before public release
labels: ["meta"]
---

## Repository & Docs
- [ ] Replace placeholder GitHub org/repo URLs in README (badges, clone, releases).
- [ ] Document supported Python versions (or justify the current 3.13+ requirement).

## CLI & Startup Experience
- [ ] Make Playwright browser installs lazy (only for render commands) to avoid heavy startup cost.
- [ ] Ensure `--quiet` suppresses all non-essential warnings (including fallback parsing).

## Recovery UX
- [ ] Map common recovery errors (HMAC, stanza parsing, invalid header) to user-friendly messages.
- [ ] Honor configured QR payload encoding for `--payloads-file` inputs (avoid forcing `auto`).

## Data Formats & Validation
- [ ] Validate manifest version in `frame_manifest.parse_manifest_frame`.
- [ ] Validate `data_frame_type` against known frame types in manifest parsing.

## Rendering & Templates
- [ ] Document “no external assets” for templates to avoid Playwright `networkidle` stalls.
- [ ] Validate fallback `line_count` earlier (config load) for clearer error messaging.

## Optional Release Hygiene
- [ ] Add SECURITY.md with vulnerability disclosure policy.
- [ ] Add CONTRIBUTING.md (setup, dev workflows, tests).
- [ ] Add CODE_OF_CONDUCT.md (community expectations).
- [ ] Add release checklist (versioning, tags, changelog, artifacts).

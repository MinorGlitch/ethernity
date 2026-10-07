# Stable v1.2 extension golden fixtures

Forge-rendered extension-chain fixtures for the unreleased v1.2 format. Newly generated
documents in the `raw` and `base64` folders use their named QR transport codec; the builder verifies
the active Backup and Add Files settings before generating either profile. The imported frozen v1.0
root keeps its historical transport bytes, so fixture extraction accepts that mixed-version chain.

## Matrix

- `raw/large_raw_two_extension_chain`: roughly 40 KiB raw root content, root
  recovery shards, and two raw incremental updates.
- `base64/gzip_replacement_chain`: gzip root and extension chunks with
  replacement, inherited files, and an empty file in the default cumulative mode.
- `base64/v1_0_root_plus_v1_2_extension`: a frozen v1.0 root with one v1.2
  extension appended.

Each guarantee appears once in the matrix. Every scenario commits rendered
documents, scanned payload fixtures, shard payload fixtures where applicable, and
a `snapshot.json` containing decoded document records and expected file hashes. The tests compare
committed file hashes and decoded records; freshly generated encrypted PDFs are not compared
byte-for-byte.

These fixtures track standalone document v3 and extension document v2, including its required
update mode. Neither current document contains an inner schema version.
Regenerate them for intentional v1.2 format or document-layout changes, then review the file
inventory and prove older root recovery remains covered. The released v1.0 root fixtures must
remain unchanged.

Regenerate with:

```bash
uv run python tests/fixtures/v1_2/extension_golden/build_golden.py
```

Generated PDFs and payload files are intentionally committed. If a fixture
version is intentionally replaced, edit the builder and regenerate instead of
hand-editing fixture files.

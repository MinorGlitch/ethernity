# Stable v1.2 extension golden fixtures

Frozen Forge-rendered extension-chain fixtures for the v1.2 compatibility profile. Newly generated
documents in the `raw` and `base64` folders use their named QR transport codec; the builder verifies
the active Backup and Add Files settings before generating either profile. The imported frozen v1.0
root keeps its historical transport bytes, so fixture extraction accepts that mixed-version chain.

## Matrix

- `raw/large_raw_two_extension_chain`: roughly 40 KiB raw root content, root
  recovery shards, and two raw extension heads.
- `base64/gzip_replacement_chain`: gzip root and extension chunks with
  replacement, inherited files, and an empty file.
- `base64/v1_0_root_plus_v1_2_extension`: a frozen v1.0 root with one v1.2
  extension appended.

Each guarantee appears once in the matrix. Every scenario commits rendered
documents, scanned payload fixtures, shard payload fixtures where applicable, and
a `snapshot.json` containing decoded document records and expected file hashes. The tests compare
committed file hashes and decoded records; freshly generated encrypted PDFs are not compared
byte-for-byte.

The committed fixtures are compatibility files. Regenerate them only for an
intentional v1.2 format or document-layout change, then review the file
inventory and prove older root recovery remains covered.

Regenerate with:

```bash
uv run python tests/fixtures/v1_2/extension_golden/build_golden.py
```

Generated PDFs and payload files are intentionally committed. If a fixture
version is intentionally replaced, edit the builder and regenerate instead of
hand-editing fixture files.

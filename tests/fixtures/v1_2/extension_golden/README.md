# Stable v1.2 Extension Golden Fixtures

Frozen Forge-rendered extension-chain fixtures for the v1.2 golden e2e matrix.

## Matrix

- `base64/large_raw_two_extension_chain` and `raw/large_raw_two_extension_chain`:
  roughly 40 KiB raw root content plus two raw extension heads.
- `base64/gzip_replacement_chain` and `raw/gzip_replacement_chain`: gzip root
  and extension chunks with replacement, inherited files, and an empty file.
- `raw/extension_local_sharded_chain`: extension-local passphrase shards plus
  extension signing-key shards.
- `raw/reuse_root_shards_chain`: root passphrase shards reused by the extension.
- `raw/loose_scan_append_chain`: renamed scan carriers and a loose append layout
  without the canonical generated `extensions/<index>` tree.
- `base64/v1_0_root_plus_v1_2_extension`: a frozen v1.0 root with one v1.2
  extension appended.

Each scenario commits rendered carriers, scanned payload fixtures, shard payload
fixtures where applicable, and a semantic `snapshot.json`. The tests compare
committed artifact hashes and semantic projections; freshly generated encrypted
PDFs are not compared byte-for-byte.

The top-level `index.json` records the SHA-256 of `build_golden.py`. If the
builder changes, regenerate the fixtures so the committed generator and fixture
matrix cannot drift silently.

Regenerate with:

```bash
uv run python tests/fixtures/v1_2/extension_golden/build_golden.py
```

Generated PDFs and payload files are intentionally committed. Edit the builder and regenerate
instead of hand-editing fixture artifacts.

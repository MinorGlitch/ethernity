# Scanner camera frames

These PNG images encode the first payload line from the frozen recovery fixtures:

- `scanner-v1-main.png`: `tests/fixtures/v1_0/golden/base64/file_no_shard/main_payloads.txt`, decoded from base64 to the original frame bytes.
- `scanner-v1-text.png`: the same line kept as base64 text.
- `scanner-v2-shard.png`: `tests/fixtures/v1_1/golden/raw/sharded_embedded/shard_payloads_threshold.txt`, decoded from base64 to the original frame bytes. Release v1.1 introduced shard format v2.

Generated with Segno, error correction M, `micro=False`, `boost_error=False`,
scale 4, border 4. Browser smoke tests draw these images in place of camera frames
and run the generated kit's actual QR decoder, normalization, and collection actions.

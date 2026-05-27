# Ethernity

Ethernity is a Python CLI for creating encrypted backup artifacts you can recover offline from
printed QR and fallback documents.

It is built for small, high-value data and deliberate recovery procedures, not continuous sync or
large bulk archives.

## Install

### pipx

```bash
pipx install ethernity-paper
```

### pip

```bash
pip install ethernity-paper
```

## First Commands

```bash
ethernity --help
ethernity backup --help
ethernity recover --help
```

## First Drill

```bash
printf "ethernity test payload\n" > payload.txt

ethernity backup \
  --input ./payload.txt \
  --output-dir ./backup-demo \
  --passphrase "ethernity test passphrase"

ethernity recover \
  --scan ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --output ./restored.txt

cmp ./payload.txt ./restored.txt
```

## Main Workflows

- `backup`: create a standalone backup set
- `recover`: restore from scans, payload files, or fallback text
- `extend`: append changes to an existing unsealed backup root
- `compact`: flatten a root plus extensions into a fresh standalone backup
- `mint`: issue new shard PDFs
- `kit`: generate a printable QR document for the browser recovery kit
- `config`: open or onboard the active TOML config
- `render`: generate helper envelopes as PDF or DOCX
- `api`: stream NDJSON for GUI clients and automation

## Useful Commands

```bash
ethernity --init-config
ethernity config --onboard
ethernity kit --variant scanner --output ./recovery_kit_scanner_qr.pdf
ethernity render envelope-c6 --format pdf --output ./envelope_c6.pdf
ethernity api inspect recover --scan ./backup-demo --passphrase "ethernity test passphrase"
```

## Links

- Source: https://github.com/MinorGlitch/ethernity
- Getting started: https://github.com/MinorGlitch/ethernity/wiki/Getting-Started
- Backup workflow: https://github.com/MinorGlitch/ethernity/wiki/Backup-Workflow
- Extension workflow: https://github.com/MinorGlitch/ethernity/wiki/Extension-Workflow
- Recovery workflow: https://github.com/MinorGlitch/ethernity/wiki/Recovery-Workflow
- Recovery kit: https://github.com/MinorGlitch/ethernity/wiki/Recovery-Kit
- Helper rendering: https://github.com/MinorGlitch/ethernity/wiki/Helper-Rendering
- Configuration: https://github.com/MinorGlitch/ethernity/wiki/Configuration-and-Defaults
- CLI API: https://github.com/MinorGlitch/ethernity/wiki/CLI-API
- Troubleshooting: https://github.com/MinorGlitch/ethernity/wiki/Troubleshooting
- Release artifacts: https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts
- Format spec: https://github.com/MinorGlitch/ethernity/blob/master/docs/format.md
- Security policy: https://github.com/MinorGlitch/ethernity/blob/master/SECURITY.md

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

## Links

- Source: https://github.com/MinorGlitch/ethernity
- Getting started: https://github.com/MinorGlitch/ethernity/wiki/Getting-Started
- Backup workflow: https://github.com/MinorGlitch/ethernity/wiki/Backup-Workflow
- Recovery workflow: https://github.com/MinorGlitch/ethernity/wiki/Recovery-Workflow
- Troubleshooting: https://github.com/MinorGlitch/ethernity/wiki/Troubleshooting
- Release artifacts: https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts
- Format spec: https://github.com/MinorGlitch/ethernity/blob/master/docs/format.md
- Security policy: https://github.com/MinorGlitch/ethernity/blob/master/SECURITY.md

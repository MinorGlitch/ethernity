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
ethernity run backup --help
ethernity run restore --help
```

## First Drill

```bash
printf "ethernity test payload\n" > payload.txt

ethernity run backup \
  --input ./payload.txt \
  --output-dir ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --yes

ethernity run restore \
  --scan ./backup-demo \
  --passphrase "ethernity test passphrase" \
  --output ./restored.txt \
  --yes

cmp ./payload.txt ./restored.txt
```

## Main Workflows

- `ethernity`: open the terminal app
- `ethernity run backup`: create a standalone backup set
- `ethernity run restore`: restore from scans, payload files, or fallback text
- `ethernity run add-files`: append files to an existing backup
- `ethernity run rebuild`: rebuild a backup from its latest recoverable state
- `ethernity run replace-recovery-docs`: create replacement recovery documents
- `ethernity run print-kit`: generate a printable QR document for the recovery kit
- `ethernity run doctor`: check local setup

## Useful Commands

```bash
ethernity
ethernity run doctor
ethernity run print-kit --variant scanner --output ./recovery_kit_scanner_qr.pdf --yes
ethernity run restore --scan ./backup-demo --passphrase "ethernity test passphrase" --preview
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
- Troubleshooting: https://github.com/MinorGlitch/ethernity/wiki/Troubleshooting
- Release artifacts: https://github.com/MinorGlitch/ethernity/wiki/Release-Artifacts
- Format spec: https://github.com/MinorGlitch/ethernity/blob/master/docs/format.md
- Security policy: https://github.com/MinorGlitch/ethernity/blob/master/SECURITY.md

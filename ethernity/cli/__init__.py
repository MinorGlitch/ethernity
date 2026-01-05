#!/usr/bin/env python3
from __future__ import annotations

from .app import app, main
from .flows.backup import BackupResult, run_backup, run_backup_command, run_wizard
from .flows.recover import run_recover_command, run_recover_wizard
from .io.frames import _frames_from_fallback
from .core.types import InputFile
from .io.inputs import _load_input_files
from .keys.recover_keys import _passphrase_from_shard_frames
from ..crypto import decrypt_bytes, encrypt_bytes, encrypt_bytes_with_passphrase, generate_identity

AUTH_FALLBACK_LABEL = "=== AUTH FRAME (z-base-32) ==="
MAIN_FALLBACK_LABEL = "=== MAIN FRAME (z-base-32) ==="

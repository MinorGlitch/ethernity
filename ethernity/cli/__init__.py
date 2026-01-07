#!/usr/bin/env python3
from __future__ import annotations

from .app import app, main
from .flows.backup import BackupResult, run_backup, run_backup_command, run_wizard
from .flows.recover import run_recover_command, run_recover_wizard
from .io.frames import _frames_from_fallback
from .core.types import InputFile
from .io.inputs import _load_input_files
from .keys.recover_keys import _passphrase_from_shard_frames
from ..crypto import decrypt_bytes, encrypt_bytes_with_passphrase

AUTH_FALLBACK_LABEL = "Auth Frame (z-base-32)"
MAIN_FALLBACK_LABEL = "Main Frame (z-base-32)"

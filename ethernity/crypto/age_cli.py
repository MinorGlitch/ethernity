#!/usr/bin/env python3
from __future__ import annotations

import functools
import os
import select
import subprocess
import tempfile
import time
from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Callable, Sequence

if os.name == "nt":
    from pyrage import passphrase as pyrage_passphrase
else:
    pyrage_passphrase = None

from ..config.installer import USER_CONFIG_DIR

from .age_fetch import download_age_binary
from .passphrases import DEFAULT_PASSPHRASE_WORDS, generate_passphrase

_fcntl = None
_pty = None
_termios = None
_USE_PTY = False
if os.name != "nt":
    try:
        _fcntl = importlib.import_module("fcntl")
        _pty = importlib.import_module("pty")
        _termios = importlib.import_module("termios")
    except Exception:
        _USE_PTY = False
        _fcntl = None
        _pty = None
        _termios = None
    else:
        _USE_PTY = True

_AGE_PATH_ENV = "ETHERNITY_AGE_PATH"
_AGE_BINARY_NAME = "age.exe" if os.name == "nt" else "age"
_AGE_BINARY_PATH = USER_CONFIG_DIR / _AGE_BINARY_NAME

@dataclass
class AgeCliError(RuntimeError):
    cmd: Sequence[str]
    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip() or "unknown error"
        return f"age failed (exit {self.returncode}): {detail}"


_PROMPT_TOKEN = b"passphrase"
_PROMPT_WINDOW = 2048
_PROMPT_TIMEOUT_SEC = 2.0


@dataclass
class _PassphraseDrainState:
    payload: bytes
    max_prompts: int
    sent: int
    deadline: float
    window: bytes


def _use_pyrage_passphrase() -> bool:
    return os.name == "nt" and pyrage_passphrase is not None


def _encrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    if pyrage_passphrase is None:
        raise RuntimeError("pyrage passphrase support is unavailable")
    return pyrage_passphrase.encrypt(data, passphrase)


def _decrypt_with_pyrage(data: bytes, passphrase: str) -> bytes:
    if pyrage_passphrase is None:
        raise RuntimeError("pyrage passphrase support is unavailable")
    return pyrage_passphrase.decrypt(data, passphrase)


def _age_preexec(
    slave_fd_int: int,
    fcntl_module,
    termios_module,
) -> None:
    os.setsid()
    fcntl_module.ioctl(slave_fd_int, termios_module.TIOCSCTTY, 0)


def _age_cmd_builder(
    output_path: str,
    input_path: str,
    *,
    age_path: str,
    decrypt: bool,
) -> Sequence[str]:
    if decrypt:
        return [age_path, "-d", "-o", output_path, input_path]
    return [age_path, "-p", "-o", output_path, input_path]


def _age_drain_with_passphrase(
    fd: int,
    proc: subprocess.Popen[bytes],
    *,
    passphrase: str,
    decrypt: bool,
) -> str:
    max_prompts = 1 if decrypt else 2
    return _drain_pty_with_passphrase(fd, proc, passphrase, max_prompts=max_prompts)


def _init_passphrase_state(passphrase: str, max_prompts: int) -> _PassphraseDrainState:
    payload = (passphrase + "\n").encode("utf-8")
    return _PassphraseDrainState(
        payload=payload,
        max_prompts=max_prompts,
        sent=0,
        deadline=time.monotonic() + _PROMPT_TIMEOUT_SEC,
        window=b"",
    )


def _passphrase_on_data(state: _PassphraseDrainState, fd: int, data: bytes) -> None:
    state.window = (state.window + data)[-_PROMPT_WINDOW:]
    if state.sent < state.max_prompts and _PROMPT_TOKEN in state.window.lower():
        _safe_write(fd, state.payload)
        state.sent += 1
        state.window = b""
        state.deadline = time.monotonic() + _PROMPT_TIMEOUT_SEC


def _passphrase_on_tick(state: _PassphraseDrainState, fd: int) -> None:
    if state.sent == 0 and time.monotonic() >= state.deadline:
        _safe_write(fd, state.payload)
        state.sent = 1
        state.deadline = time.monotonic() + _PROMPT_TIMEOUT_SEC


def encrypt_bytes_with_passphrase(
    data: bytes,
    *,
    passphrase: str | None = None,
    passphrase_words: int | None = None,
) -> tuple[bytes, str | None]:
    if passphrase:
        if _use_pyrage_passphrase():
            ciphertext = _encrypt_with_pyrage(data, passphrase)
            return ciphertext, passphrase
        age_path = get_age_path()
        ciphertext = _run_age_encrypt_passphrase(data, passphrase=passphrase, age_path=age_path)
        return ciphertext, passphrase

    words = DEFAULT_PASSPHRASE_WORDS if passphrase_words is None else passphrase_words
    generated = generate_passphrase(words=words)
    if _use_pyrage_passphrase():
        ciphertext = _encrypt_with_pyrage(data, generated)
        return ciphertext, generated
    age_path = get_age_path()
    ciphertext = _run_age_encrypt_passphrase(data, passphrase=generated, age_path=age_path)
    return ciphertext, generated


def decrypt_bytes(
    data: bytes,
    *,
    passphrase: str,
) -> bytes:
    if _use_pyrage_passphrase():
        return _decrypt_with_pyrage(data, passphrase)
    age_path = get_age_path()
    return _run_age_decrypt_passphrase(data, passphrase=passphrase, age_path=age_path)


def get_age_path() -> str:
    env_path = os.environ.get(_AGE_PATH_ENV)
    if env_path:
        return env_path
    if _AGE_BINARY_PATH.exists():
        return str(_AGE_BINARY_PATH)
    return "age"


def ensure_age_binary() -> str:
    env_path = os.environ.get(_AGE_PATH_ENV)
    if env_path:
        resolved = Path(env_path).expanduser()
        if not resolved.exists():
            raise RuntimeError(f"age binary not found at {resolved}")
        return str(resolved)
    if _AGE_BINARY_PATH.exists():
        return str(_AGE_BINARY_PATH)
    _AGE_BINARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    download_age_binary(
        dest_path=_AGE_BINARY_PATH,
        binary_name=_AGE_BINARY_NAME,
        path_env=_AGE_PATH_ENV,
    )
    return str(_AGE_BINARY_PATH)


def _run_age(cmd: Sequence[str], data: bytes) -> bytes:
    proc = subprocess.run(
        list(cmd),
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AgeCliError(
            cmd=list(cmd),
            returncode=proc.returncode,
            stderr=proc.stderr.decode("utf-8", errors="replace"),
        )
    return proc.stdout


def _run_age_with_pty(
    *,
    cmd_builder: Callable[[str, str], Sequence[str]],
    data: bytes,
    drain: Callable[[int, subprocess.Popen[bytes]], str],
) -> tuple[bytes, str]:
    if not _USE_PTY:
        raise RuntimeError("PTY-based age handling is not available on this platform")
    pty = _pty
    fcntl = _fcntl
    termios = _termios
    assert pty is not None
    assert fcntl is not None
    assert termios is not None
    input_path = None
    output_path = None
    master_fd = None
    slave_fd = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as infile:
            infile.write(data)
            input_path = infile.name
        with tempfile.NamedTemporaryFile(delete=False) as outfile:
            output_path = outfile.name

        master_fd, slave_fd = pty.openpty()
        slave_fd_int: int = slave_fd

        cmd = list(cmd_builder(output_path, input_path))
        preexec_fn = functools.partial(_age_preexec, slave_fd_int, fcntl, termios)
        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=subprocess.DEVNULL,
            stderr=slave_fd,
            preexec_fn=preexec_fn,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = None

        tty_output = drain(master_fd, proc)
        returncode = proc.wait()
        if returncode != 0:
            raise AgeCliError(cmd=cmd, returncode=returncode, stderr=tty_output)

        with open(output_path, "rb") as handle:
            output = handle.read()

        return output, tty_output
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if slave_fd is not None:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        if input_path:
            _safe_unlink(input_path)
        if output_path:
            _safe_unlink(output_path)


def _run_age_with_subprocess(
    *,
    cmd_builder: Callable[[str, str], Sequence[str]],
    data: bytes,
    passphrase: str,
    prompt_count: int,
) -> tuple[bytes, str]:
    input_path = None
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as infile:
            infile.write(data)
            input_path = infile.name
        with tempfile.NamedTemporaryFile(delete=False) as outfile:
            output_path = outfile.name

        cmd = list(cmd_builder(output_path, input_path))
        env = os.environ.copy()
        env["AGE_PASSPHRASE"] = passphrase
        payload = ((passphrase + "\n") * max(1, prompt_count)).encode("utf-8")
        proc = subprocess.run(
            cmd,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise AgeCliError(cmd=cmd, returncode=proc.returncode, stderr=stderr)

        with open(output_path, "rb") as handle:
            output = handle.read()

        return output, stderr
    finally:
        if input_path:
            _safe_unlink(input_path)
        if output_path:
            _safe_unlink(output_path)


def _run_age_encrypt_passphrase(data: bytes, *, passphrase: str, age_path: str) -> bytes:
    return _run_age_passphrase(data, passphrase=passphrase, age_path=age_path, decrypt=False)


def _run_age_decrypt_passphrase(data: bytes, *, passphrase: str, age_path: str) -> bytes:
    return _run_age_passphrase(data, passphrase=passphrase, age_path=age_path, decrypt=True)


def _run_age_passphrase(
    data: bytes,
    *,
    passphrase: str,
    age_path: str,
    decrypt: bool,
) -> bytes:
    cmd_builder = functools.partial(_age_cmd_builder, age_path=age_path, decrypt=decrypt)
    drain = functools.partial(_age_drain_with_passphrase, passphrase=passphrase, decrypt=decrypt)

    if _USE_PTY:
        output, _tty_output = _run_age_with_pty(
            cmd_builder=cmd_builder,
            data=data,
            drain=drain,
        )
    else:
        prompt_count = 1 if decrypt else 2
        output, _tty_output = _run_age_with_subprocess(
            cmd_builder=cmd_builder,
            data=data,
            passphrase=passphrase,
            prompt_count=prompt_count,
        )
    return output


def _drain_pty(fd: int, proc: subprocess.Popen[bytes]) -> str:
    return _drain_pty_loop(fd, proc)


def _drain_pty_loop(
    fd: int,
    proc: subprocess.Popen[bytes],
    *,
    on_data: Callable[[bytes], None] | None = None,
    on_tick: Callable[[], None] | None = None,
) -> str:
    chunks: list[bytes] = []
    while True:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if fd in ready:
            try:
                data = os.read(fd, 1024)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
            if on_data:
                on_data(data)
        if on_tick:
            on_tick()
        if proc.poll() is not None:
            while True:
                try:
                    data = os.read(fd, 1024)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
                if on_data:
                    on_data(data)
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def _drain_pty_with_passphrase(
    fd: int, proc: subprocess.Popen[bytes], passphrase: str, *, max_prompts: int = 1
) -> str:
    state = _init_passphrase_state(passphrase, max_prompts)
    on_data = functools.partial(_passphrase_on_data, state, fd)
    on_tick = functools.partial(_passphrase_on_tick, state, fd)
    return _drain_pty_loop(fd, proc, on_data=on_data, on_tick=on_tick)


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_write(fd: int, data: bytes) -> None:
    try:
        os.write(fd, data)
    except OSError:
        pass

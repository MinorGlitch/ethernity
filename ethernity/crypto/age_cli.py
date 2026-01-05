#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
import pty
import select
import subprocess
import tempfile
import time
import termios
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .passphrases import DEFAULT_PASSPHRASE_WORDS, generate_passphrase

@dataclass
class AgeCliError(RuntimeError):
    cmd: Sequence[str]
    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip() or "unknown error"
        return f"age failed (exit {self.returncode}): {detail}"


@dataclass
class AgeKeygenError(RuntimeError):
    cmd: Sequence[str]
    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip() or "unknown error"
        return f"age-keygen failed (exit {self.returncode}): {detail}"


def parse_recipients(text: str) -> list[str]:
    return _parse_lines(text)


def parse_identities(text: str) -> list[str]:
    return _parse_lines(text)


def encrypt_bytes(
    data: bytes,
    *,
    recipients: Sequence[str] | None = None,
    passphrase: str | None = None,
    age_path: str = "age",
) -> bytes:
    if (recipients is None) == (passphrase is None):
        raise ValueError("set exactly one of recipients or passphrase")

    if passphrase is not None:
        return _run_age_encrypt_passphrase(data, passphrase=passphrase, age_path=age_path)

    recipients = list(recipients or [])
    if not recipients:
        raise ValueError("recipients cannot be empty")
    cmd = [age_path]
    for recipient in recipients:
        cmd.extend(["-r", recipient])

    return _run_age(cmd, data)


def encrypt_bytes_with_passphrase(
    data: bytes,
    *,
    passphrase: str | None = None,
    passphrase_words: int | None = None,
    age_path: str = "age",
) -> tuple[bytes, str | None]:
    if passphrase:
        ciphertext = _run_age_encrypt_passphrase(data, passphrase=passphrase, age_path=age_path)
        return ciphertext, passphrase

    words = DEFAULT_PASSPHRASE_WORDS if passphrase_words is None else passphrase_words
    generated = generate_passphrase(words=words)
    ciphertext = _run_age_encrypt_passphrase(data, passphrase=generated, age_path=age_path)
    return ciphertext, generated


def decrypt_bytes(
    data: bytes,
    *,
    identities: Sequence[str] | None = None,
    passphrase: str | None = None,
    age_path: str = "age",
) -> bytes:
    if (identities is None) == (passphrase is None):
        raise ValueError("set exactly one of identities or passphrase")

    if passphrase is not None:
        return _run_age_decrypt_passphrase(data, passphrase=passphrase, age_path=age_path)

    cmd = [age_path, "-d"]
    temp_path = None

    try:
        identities = list(identities or [])
        if not identities:
            raise ValueError("identities cannot be empty")
        temp_path = _write_temp_identities(identities)
        cmd.extend(["-i", temp_path])

        return _run_age(cmd, data)
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def generate_identity(age_keygen_path: str = "age-keygen") -> tuple[str, str]:
    proc = subprocess.run(
        [age_keygen_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AgeKeygenError(
            cmd=[age_keygen_path],
            returncode=proc.returncode,
            stderr=proc.stderr.decode("utf-8", errors="replace"),
        )

    output = "\n".join(
        [
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        ]
    )
    identity = None
    recipient = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("AGE-SECRET-KEY-"):
            identity = stripped
        if "public key:" in stripped:
            recipient = stripped.split("public key:", 1)[1].strip()
        if "recipient:" in stripped:
            recipient = stripped.split("recipient:", 1)[1].strip()

    if not identity or not recipient:
        raise ValueError("failed to parse age-keygen output")

    return identity, recipient


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

        def _preexec() -> None:
            os.setsid()
            fcntl.ioctl(slave_fd_int, termios.TIOCSCTTY, 0)

        cmd = list(cmd_builder(output_path, input_path))
        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=subprocess.DEVNULL,
            stderr=slave_fd,
            preexec_fn=_preexec,
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
    def _builder(output_path: str, input_path: str) -> Sequence[str]:
        if decrypt:
            return [age_path, "-d", "-o", output_path, input_path]
        return [age_path, "-p", "-o", output_path, input_path]

    def _drain(fd: int, proc: subprocess.Popen[bytes]) -> str:
        max_prompts = 1 if decrypt else 2
        return _drain_pty_with_passphrase(fd, proc, passphrase, max_prompts=max_prompts)

    output, _tty_output = _run_age_with_pty(
        cmd_builder=_builder,
        data=data,
        drain=_drain,
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
    sent = 0
    deadline = time.monotonic() + 2.0
    window = b""
    prompt_token = b"passphrase"
    payload = (passphrase + "\n").encode("utf-8")

    def _on_data(data: bytes) -> None:
        nonlocal sent, window, deadline
        window = (window + data)[-2048:]
        if sent < max_prompts and prompt_token in window.lower():
            _safe_write(fd, payload)
            sent += 1
            window = b""
            deadline = time.monotonic() + 2.0

    def _on_tick() -> None:
        nonlocal sent, deadline
        if sent == 0 and time.monotonic() >= deadline:
            _safe_write(fd, payload)
            sent = 1
            deadline = time.monotonic() + 2.0

    return _drain_pty_loop(fd, proc, on_data=_on_data, on_tick=_on_tick)


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


def _parse_lines(text: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        values.append(stripped)
    return values


def _write_temp_identities(identities: Iterable[str]) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        for identity in identities:
            handle.write(identity.rstrip() + "\n")
        return handle.name

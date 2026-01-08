#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import select
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import tarfile
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..config.installer import USER_CONFIG_DIR

from .passphrases import DEFAULT_PASSPHRASE_WORDS, generate_passphrase
import certifi

_USE_PTY = False
if os.name != "nt":
    try:
        import fcntl as _fcntl
        import pty as _pty
        import termios as _termios
    except ImportError:
        _USE_PTY = False
        _fcntl = None
        _pty = None
        _termios = None
    else:
        _USE_PTY = True
else:
    _fcntl = None
    _pty = None
    _termios = None

_AGE_VERSION = "1.3.1"
_AGE_REPO = "FiloSottile/age"
_AGE_PATH_ENV = "ETHERNITY_AGE_PATH"
_AGE_BINARY_NAME = "age.exe" if os.name == "nt" else "age"
_AGE_BINARY_PATH = USER_CONFIG_DIR / _AGE_BINARY_NAME
_AGE_ARTIFACTS = {
    ("darwin", "arm64"),
    ("freebsd", "amd64"),
    ("linux", "amd64"),
    ("linux", "arm"),
    ("linux", "arm64"),
    ("windows", "amd64"),
}

@dataclass
class AgeCliError(RuntimeError):
    cmd: Sequence[str]
    returncode: int
    stderr: str

    def __str__(self) -> str:
        detail = self.stderr.strip() or "unknown error"
        return f"age failed (exit {self.returncode}): {detail}"


def encrypt_bytes_with_passphrase(
    data: bytes,
    *,
    passphrase: str | None = None,
    passphrase_words: int | None = None,
) -> tuple[bytes, str | None]:
    age_path = get_age_path()
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
    passphrase: str,
) -> bytes:
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
    archive_name, url, archive_kind = _age_download_spec()
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / archive_name
        _download_file(url, archive_path)
        tmp_binary = Path(tmpdir) / _AGE_BINARY_NAME
        if archive_kind == "zip":
            _extract_from_zip(archive_path, tmp_binary, _AGE_BINARY_NAME)
        else:
            _extract_from_tar(archive_path, tmp_binary, _AGE_BINARY_NAME)
        tmp_binary.replace(_AGE_BINARY_PATH)
    if os.name != "nt":
        os.chmod(_AGE_BINARY_PATH, 0o755)
    return str(_AGE_BINARY_PATH)


def _age_download_spec() -> tuple[str, str, str]:
    os_name = _age_platform_name()
    arch = _age_arch_name()
    if (os_name, arch) not in _AGE_ARTIFACTS:
        supported = ", ".join(sorted(f"{name}-{cpu}" for name, cpu in _AGE_ARTIFACTS))
        raise RuntimeError(
            f"age release does not include {os_name}-{arch}. Supported: {supported}. "
            f"Set {_AGE_PATH_ENV} to a local age binary."
        )
    if os_name == "windows":
        archive_kind = "zip"
        archive_name = f"age-v{_AGE_VERSION}-{os_name}-{arch}.zip"
    else:
        archive_kind = "tar.gz"
        archive_name = f"age-v{_AGE_VERSION}-{os_name}-{arch}.tar.gz"
    url = f"https://github.com/{_AGE_REPO}/releases/download/v{_AGE_VERSION}/{archive_name}"
    return archive_name, url, archive_kind


def _age_platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("freebsd"):
        return "freebsd"
    raise RuntimeError(f"unsupported platform for age download: {sys.platform}")


def _age_arch_name() -> str:
    if sys.platform == "win32":
        return "amd64"
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("arm", "armv6", "armv6l", "armv7", "armv7l", "armv8l", "armhf"):
        return "arm"
    raise RuntimeError(f"unsupported architecture for age download: {machine}")


def _download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ethernity"})
    context = ssl.create_default_context(cafile=certifi.where())
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=60, context=context) as resp:
                with open(dest, "wb") as handle:
                    shutil.copyfileobj(resp, handle)
            return
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(1.5 * attempt)
                continue
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                detail = f"HTTP {exc.code} {exc.reason}"
            elif isinstance(exc, urllib.error.URLError):
                detail = str(exc.reason)
            raise RuntimeError(f"failed to download age from {url}: {detail}") from exc


def _extract_from_zip(archive_path: Path, dest: Path, binary_name: str) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(f"/{binary_name}") or name == binary_name
            ),
            None,
        )
        if member is None:
            raise RuntimeError("age binary not found in zip archive")
        with archive.open(member) as src, open(dest, "wb") as handle:
            shutil.copyfileobj(src, handle)


def _extract_from_tar(archive_path: Path, dest: Path, binary_name: str) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        member = next(
            (
                entry
                for entry in archive.getmembers()
                if entry.isfile()
                and (entry.name.endswith(f"/{binary_name}") or entry.name == binary_name)
            ),
            None,
        )
        if member is None:
            raise RuntimeError("age binary not found in tar archive")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("failed to extract age binary from tar archive")
        with extracted, open(dest, "wb") as handle:
            shutil.copyfileobj(extracted, handle)


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
    def _builder(output_path: str, input_path: str) -> Sequence[str]:
        if decrypt:
            return [age_path, "-d", "-o", output_path, input_path]
        return [age_path, "-p", "-o", output_path, input_path]

    def _drain(fd: int, proc: subprocess.Popen[bytes]) -> str:
        max_prompts = 1 if decrypt else 2
        return _drain_pty_with_passphrase(fd, proc, passphrase, max_prompts=max_prompts)

    if _USE_PTY:
        output, _tty_output = _run_age_with_pty(
            cmd_builder=_builder,
            data=data,
            drain=_drain,
        )
    else:
        prompt_count = 1 if decrypt else 2
        output, _tty_output = _run_age_with_subprocess(
            cmd_builder=_builder,
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

"""Verified updates; keep old program directories for recovery."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid
import zipfile
from . import config as cfg

logger = logging.getLogger(__name__)
CHECKING, DOWNLOADING, READY, FAILED = "checking", "downloading", "ready", "failed"

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))

def current_exe() -> Path:
    return Path(sys.executable).resolve()

def install_root() -> Path:
    return current_exe().parent

def update_dir() -> Path:
    path = cfg.config_dir() / "update"
    path.mkdir(parents=True, exist_ok=True)
    return path

def _version(value: str) -> str:
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", value):
        raise ValueError("Invalid update version")
    return value

def staged_path(version: str) -> Path:
    return update_dir() / f"SevimliKassa-{_version(version)}.zip"

def run_flag() -> Path:
    return update_dir() / "run-ok"

def mark_started() -> None:
    """Called by Qt after the main window and login view exist."""
    try:
        from .version import VERSION
        run_flag().write_text(VERSION, encoding="utf-8")  # previous updater compatibility
        ready = update_dir() / "run-ready.json"
        temp = ready.with_name("run-ready-" + uuid.uuid4().hex + ".tmp")
        temp.write_text(json.dumps({"pid": os.getpid(), "version": VERSION,
                                   "nonce": os.environ.get("SEVIMLI_UPDATE_NONCE", "")}), encoding="utf-8")
        temp.replace(ready)
    except OSError:
        logger.exception("Could not write UI readiness marker")

def cleanup(keep: str = "") -> None:
    """Remove old downloads only. Preserve recovery directories and plans."""
    try:
        for path in update_dir().glob("SevimliKassa-*.zip*"):
            if keep and path.name.startswith(f"SevimliKassa-{keep}.zip"):
                continue
            if path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)
    except OSError:
        logger.info("Old download cleanup deferred")

def _extract(zip_path: Path, version: str) -> Path | None:
    try:
        version = _version(version)
        dest = update_dir() / f"new-{version}-{uuid.uuid4().hex}"
        with zipfile.ZipFile(zip_path) as archive:
            for item in archive.infolist():
                name = item.filename
                parts = PurePosixPath(name).parts
                if (not parts or "\\" in name or name.startswith("/")
                        or any(part in (".", "..") or ":" in part or part.endswith((" ", ".")) for part in parts)
                        or stat.S_ISLNK(item.external_attr >> 16)):
                    raise ValueError("Unsafe ZIP path")
            dest.mkdir(exist_ok=False)
            archive.extractall(dest)
        found = list(dest.rglob("SevimliKassa.exe"))
        if len(found) != 1 or not any((found[0].parent / "_internal").glob("python3*.dll")):
            raise ValueError("Incomplete or ambiguous application package")
        return found[0].parent
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        logger.error("Update archive rejected: %s", exc)
        return None

def apply(zip_path: Path) -> bool:
    """True means the worker started; caller must exit normally."""
    zip_path = Path(zip_path)
    if not zip_path.is_file() or not is_frozen() or os.name != "nt":
        logger.warning("Update not applicable: %s", zip_path)
        return False
    from . import installer
    target = install_root()
    if target != installer.install_dir().resolve():
        logger.error("Refusing unexpected installation directory")
        return False
    version = zip_path.stem.removeprefix("SevimliKassa-")
    new_dir = _extract(zip_path, version)
    if new_dir is None:
        return False
    try:
        from .update_worker import runtime_check
        # Verify worker runtime before closing this register, only on explicit update.
        runtime_check(new_dir / "SevimliKassa.exe", update_dir() / ("preflight-" + uuid.uuid4().hex))
        plan = update_dir() / ("apply-" + uuid.uuid4().hex + ".json")
        plan.write_text(json.dumps({"source": str(new_dir), "target": str(target),
                                    "pid": os.getpid(), "version": version}), encoding="utf-8")
        subprocess.Popen([str(new_dir / "SevimliKassa.exe"), "--apply-update", str(plan)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         close_fds=True, cwd=str(new_dir))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.error("Update worker could not start: %s", exc)
        return False
    return True

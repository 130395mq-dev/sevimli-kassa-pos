"""Verified directory replacement. Failed/previous versions are kept for recovery.

Application data lives separately in APPDATA and is never copied or replaced here.
All renames are between verified siblings; no recursive removal is performed.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import uuid


def _plain_tree(root: Path) -> None:
    # Refuse junctions/symlinks, including a redirected installation parent.
    for item in (root, *root.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError(f'Redirected application path: {item}')
    for item in root.rglob('*'):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError(f'Redirected application file: {item}')


def manifest(root: Path) -> dict[str, str]:
    _plain_tree(root)
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_file():
            with p.open('rb') as stream:
                result[p.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def stage(source: Path, target: Path) -> Path:
    source, target = Path(source).absolute(), Path(target).absolute()
    _plain_tree(source)
    _plain_tree(target)
    source, target = source.resolve(), target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Source and target must be separate application directories')
    if not (source / 'SevimliKassa.exe').is_file():
        raise ValueError('Application executable missing')
    if not any((source / '_internal').glob('python3*.dll')):
        raise ValueError('Application runtime missing')
    before = manifest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name('.' + target.name + '-staging-' + uuid.uuid4().hex)
    # Unique sibling, never overlay. A partial copy stays available for diagnosis.
    shutil.copytree(source, staged)
    if manifest(staged) != before or manifest(source) != before:
        raise OSError('Application copy verification failed')
    return staged


def _siblings(target: Path, other: Path) -> tuple[Path, Path]:
    target, other = Path(target).absolute(), Path(other).absolute()
    _plain_tree(target)
    _plain_tree(other)
    target, other = target.resolve(), other.resolve()
    if target.parent != other.parent or target == other or target == target.parent:
        raise ValueError('Application replacement requires distinct sibling directories')
    return target, other


def activate(staged: Path, target: Path) -> Path | None:
    target, staged = _siblings(target, staged)
    backup = None
    if target.exists():
        backup = target.with_name('.' + target.name + '-backup-' + uuid.uuid4().hex)
        target.rename(backup)  # Failure stops before touching the existing install.
    try:
        staged.rename(target)
    except BaseException:
        if backup is not None:
            backup.rename(target)
        raise
    return backup


def rollback(target: Path, backup: Path) -> Path:
    target, backup = _siblings(target, backup)
    if not (backup / 'SevimliKassa.exe').is_file():
        raise ValueError('Recovery executable missing')
    failed = target.with_name('.' + target.name + '-failed-' + uuid.uuid4().hex)
    if target.exists():
        target.rename(failed)
    try:
        backup.rename(target)
    except BaseException:
        if failed.exists() and not target.exists():
            failed.rename(target)
        raise
    return failed


@contextmanager
def register_closed(name: str = 'SevimliKassa'):
    """Fail closed when another POS owns the Windows single-instance name."""
    if os.name != 'nt':
        yield
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.CreateMutexW(None, False, 'Local\\' + name)
    if not handle:
        raise OSError(ctypes.get_last_error(), 'Could not verify that the register is closed')
    try:
        if ctypes.get_last_error() == 183:
            raise RuntimeError('Avval ochiq Sevimli Kassa oynasidan Chiqish qiling')
        yield
    finally:
        kernel.CloseHandle(handle)

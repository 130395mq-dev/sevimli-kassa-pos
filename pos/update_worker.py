"""Detached updater, run from the newly extracted EXE, never from TARGET.

It never force-stops a trading register. A running but unconfirmed new process
is left running, with the previous directory retained for manual recovery.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from . import deployment


def wait_parent(pid: int, timeout: float = 120) -> None:
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
    if not handle:
        if ctypes.get_last_error() == 87:  # already exited
            return
        raise OSError(ctypes.get_last_error(), 'Cannot wait for original register')
    try:
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise TimeoutError('Original register did not close; installation unchanged')
    finally:
        kernel.CloseHandle(handle)


def runtime_check(exe: Path, result_dir: Path) -> None:
    completed = subprocess.run(
        [str(exe), '--check-runtime', str(result_dir)], timeout=60,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    result = json.loads((result_dir / 'result.json').read_text(encoding='utf-8'))
    if completed.returncode or not result.get('ok') or not result.get('frozen') or result.get('integrity') != 'ok':
        raise RuntimeError('New EXE failed isolated runtime verification')


def start_register(target: Path, nonce: str = ''):
    env = dict(os.environ)
    env['SEVIMLI_UPDATE_NONCE'] = nonce
    return subprocess.Popen([str(target / 'SevimliKassa.exe')], cwd=str(target), env=env,
                            close_fds=True)


def await_ready(process, ready: Path, version: str, nonce: str, seconds: float = 120) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            value = json.loads(ready.read_text(encoding='utf-8'))
            if value == {'pid': process.pid, 'version': version, 'nonce': nonce}:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    return False


def perform(source: Path, target: Path, state_dir: Path, version: str,
            *, ready_timeout: float = 120) -> dict:
    """Called only after the original process exits; all states are recoverable."""
    report = {'status': 'preparing', 'backup': None, 'worker_writes_register_database': False}
    backup = None
    activated = False
    child = None
    try:
        with deployment.register_closed():
            staged = deployment.stage(source, target)
            report['staged'] = str(staged)
            runtime_check(staged / 'SevimliKassa.exe', state_dir / ('runtime-' + uuid.uuid4().hex))
            backup = deployment.activate(staged, target)
            activated = True
            report['backup'] = str(backup) if backup else None
        nonce = uuid.uuid4().hex
        child = start_register(target, nonce)
        report['pid'] = child.pid
        if await_ready(child, state_dir / 'run-ready.json', version, nonce, ready_timeout):
            report['status'] = 'updated'
        elif child.poll() is None:
            # Never kill or launch a second POS when the first might be trading.
            report['status'] = 'running-unconfirmed-backup-retained'
        else:
            raise RuntimeError('New register exited before UI readiness')
    except Exception as exc:
        report['error'] = str(exc)
        # Do not touch an installation if the process may have begun trading.
        if child is not None and child.poll() is None:
            report['status'] = 'running-unconfirmed-backup-retained'
            return report
        try:
            with deployment.register_closed():
                if activated and backup:
                    report['failed'] = str(deployment.rollback(target, backup))
                    report['status'] = 'rolled-back'
                elif not activated:
                    report['status'] = 'unchanged'
                else:
                    report['status'] = 'failed-no-previous-install'
            if report['status'] in ('rolled-back', 'unchanged') and (target / 'SevimliKassa.exe').exists():
                report['restarted_pid'] = start_register(target).pid
        except Exception as recovery_exc:
            report['status'] = 'recovery-required'
            report['recovery_error'] = str(recovery_exc)
    return report


def run(plan_file: str) -> int:
    from . import config, installer
    state_dir = config.config_dir() / 'update'
    plan_path = Path(plan_file).resolve()
    if plan_path.parent != state_dir.resolve() or not plan_path.name.startswith('apply-'):
        raise ValueError('Update plan must be in the register update directory')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    source = Path(plan['source']).resolve()
    target = Path(plan['target']).resolve()
    if state_dir.resolve() not in source.parents or target != installer.install_dir().resolve():
        raise ValueError('Update path is outside the designated directories')
    try:
        with deployment.register_closed('SevimliKassa-Update'):
            wait_parent(int(plan['pid']))
            report = perform(source, target, state_dir, str(plan['version']))
    except Exception as exc:
        report = {'status': 'unchanged', 'error': str(exc)}
    plan_path.with_suffix('.result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'updated' else 1

"""
O'zini o'rnatish — dastur bir papka (onedir), alohida o'rnatuvchi yo'q.

Dastur `SevimliKassa` papkasi ichida keladi: SevimliKassa.exe va yonida
`_internal/` (python312.dll va boshqalar). Fleshkadan yoki yuklab olib
ochilgan papkadan SevimliKassa.exe birinchi ishga tushganda o'zini
tekshiradi:

    Men o'rnatilgan joydan (%LOCALAPPDATA%\\SevimliKassa) ishlayapmanmi?
      ha  → oddiy ishlayveradi
      yo'q → BUTUN PAPKANI o'sha joyga nusxalaydi, ish stolida va avto-ishga
             tushishda yorliq yaratadi, o'rnatilgan nusxani ochadi, o'zi yopiladi

Login-parol o'rnatilgan nusxa ochilganda so'raladi. Server manzili
so'ralmaydi — u dasturning ichida (config.DEFAULT_SERVER).

Yig'ilmagan holda (python -m pos.main) hech narsa qilmaydi.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "Sevimli Kassa"
EXE_NAME = "SevimliKassa.exe"


class InstallError(RuntimeError):
    pass


def app_dir() -> Path:
    """Hozir ishlayotgan dastur papkasi (exe va _internal shu yerda)."""
    return Path(sys.executable).resolve().parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "SevimliKassa"


def installed_exe() -> Path:
    return install_dir() / EXE_NAME


def is_installed_copy() -> bool:
    """Hozir ishlayotgan exe — o'rnatilgan nusxami?"""
    try:
        return Path(sys.executable).resolve() == installed_exe().resolve()
    except OSError:
        return False


_SHORTCUTS_PS = r"""
$w = New-Object -ComObject WScript.Shell
$target = '{exe}'
$dir = '{dir}'
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Startup'))) {{
  $s = $w.CreateShortcut((Join-Path $folder '{name}.lnk'))
  $s.TargetPath = $target
  $s.WorkingDirectory = $dir
  $s.Description = '{name}'
  $s.Save()
}}
"""


def _make_shortcuts(exe: Path) -> None:
    script = _SHORTCUTS_PS.format(exe=str(exe).replace("'", "''"),
                                  dir=str(exe.parent).replace("'", "''"), name=APP_NAME)
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=creation, timeout=30, check=False,
    )


def ensure_autostart() -> None:
    """Kassa Windows'ga har kirganda o'zi ochiladi.

    Startup papkasidagi yorliq ba'zi terminallarда yaratilmay qolgan
    (PowerShell cheklangan bo'lsa). Shuning uchun ishonchli yo'l —
    ro'yxatga (Run) yozib qo'yish: `reg add` PowerShell'siz ishlaydi.

    Har ochilishда chaqiriladi (arzon) — yozuv yo'q bo'lsa qayta yaratadi.
    Shu tufayli kassa yopilsa yoki monoblok o'chib-yonsa — o'zi qaytadi.
    """
    if not is_frozen():
        return
    exe = installed_exe()
    if not exe.exists():
        exe = Path(sys.executable)
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["reg", "add",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
             "/v", "SevimliKassa", "/t", "REG_SZ", "/d", '"' + str(exe) + '"', "/f"],
            creationflags=creation, timeout=15, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # avtoyuklanish yo'q bo'lsa ham kassa ishlayveradi
        logger.info("Avtoyuklanish yozilmadi: %s", e)


def ensure_installed() -> bool:
    """Install a verified directory; never force-close an open register.

    False: source mode/already installed. True: installed process owns startup.
    Failure raises InstallError so an uninstalled copy cannot silently trade.
    """
    if not is_frozen() or is_installed_copy():
        return False
    import json
    import uuid
    from . import updater, update_worker, deployment
    from .version import VERSION
    try:
        with deployment.register_closed('SevimliKassa-Update'):
            result = update_worker.perform(app_dir(), install_dir(), updater.update_dir(), VERSION)
        report = updater.update_dir() / ('install-' + uuid.uuid4().hex + '.result.json')
        report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    except Exception as exc:
        raise InstallError(str(exc)) from exc
    if result['status'] not in ('updated', 'running-unconfirmed-backup-retained'):
        raise InstallError('Ornatish yakunlanmadi. Eski nusxa saqlandi.\n' + result.get('error', result['status']))
    # Cosmetic integration must not roll back a healthy register.
    try:
        _make_shortcuts(installed_exe())
    except Exception:
        logger.exception('Could not create shortcuts; installed register is running')
    return True

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
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "Sevimli Kassa"
EXE_NAME = "SevimliKassa.exe"


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
    script = _SHORTCUTS_PS.format(exe=str(exe), dir=str(exe.parent), name=APP_NAME)
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
             "/v", "SevimliKassa", "/t", "REG_SZ", "/d", str(exe), "/f"],
            creationflags=creation, timeout=15, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # avtoyuklanish yo'q bo'lsa ham kassa ishlayveradi
        logger.info("Avtoyuklanish yozilmadi: %s", e)


def _kill_other_instances() -> None:
    """O'rnatilgan nusxa ishlab turgan bo'lsa — yopamiz, aks holda ustidan
    yozib bo'lmaydi (Windows ishlayotgan exe ni qulflaydi)."""
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["taskkill", "/F", "/IM", EXE_NAME, "/FI", f"PID ne {os.getpid()}"],
        creationflags=creation, timeout=15, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def ensure_installed() -> bool:
    """O'rnatilgan joydan ishlamayotgan bo'lsak — o'rnatadi va o'rnatilgan
    nusxani ishga tushiradi.

    onedir bo'lgani uchun BUTUN PAPKA ko'chiriladi (exe + _internal).

    True qaytarsa — chaqiruvchi DARHOL chiqishi kerak (o'rnatilgan nusxa
    ochilib bo'ldi). False — davom etaveramiz (yig'ilmagan muhit, yoki
    allaqachon o'rnatilgan joydamiz, yoki o'rnatib bo'lmadi).
    """
    if not is_frozen() or is_installed_copy():
        return False

    src_dir = app_dir()
    dest_dir = install_dir()
    dest_exe = installed_exe()
    try:
        _kill_other_instances()
        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        # Butun papkani ko'chiramiz. dirs_exist_ok=True — eski o'rnatma
        # ustiga yozadi (fayllar almashtiriladi). Ishlayotgan nusxa
        # yo'q (yuqorida yopdik), shuning uchun qulf muammosi yo'q.
        shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
        _make_shortcuts(dest_exe)
        ensure_autostart()
    except Exception as e:
        logger.error("O'zini o'rnatib bo'lmadi: %s", e)
        return False

    logger.info("O'rnatildi: %s", dest_dir)
    try:
        creation = getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([str(dest_exe)], cwd=str(dest_dir), close_fds=True,
                         creationflags=creation)
    except OSError as e:
        logger.error("O'rnatilgan nusxa ochilmadi: %s", e)
        return False
    return True

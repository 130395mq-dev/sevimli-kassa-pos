"""
Ilovaning o'zini yangilashi.

Oqim:

    1. Fon oqimi serverdan versiyani so'raydi (ochilganda, keyin har 30 daq).
    2. Kattaroq versiya bo'lsa — yangi dastur ZIP fon oqimida yuklab
       olinadi (%APPDATA%\\SevimliKassa\\update\\SevimliKassa-1.4.0.zip),
       SHA-256 tekshiriladi. Kassir bu paytda bemalol ishlaydi.
    3. Tayyor bo'lgach oyna chiqadi: «Yangilash» / «Keyinroq».
       Majburiy bo'lsa «Keyinroq» yo'q — chek yakunlangach o'zi yangilanadi.
    4. `apply()` — dastur endi bir PAPKA (onedir): exe + _internal. ZIP
       ochiladi, ichi tekshiriladi (SevimliKassa.exe va python312.dll
       bor-yo'qligi), so'ng kichik .bat yoziladi: u ilova yopilishini
       kutadi, yangi papkani o'rnatilgan papka ustiga ko'chiradi
       (robocopy) va ilovani qayta ochadi. Ilova esa shunchaki chiqadi.

Nega robocopy: ishlayotgan exe qulflangan bo'ladi, robocopy uni bo'shaguncha
qayta urinadi va butun papkani ishonchli ko'chiradi. Ko'chirish chala
bo'lsa — ZIP ichi oldindan tekshirilgani uchun buzuq papka o'rnatilmaydi.

Yig'ilmagan holda (python -m pos.main) hech narsa almashtirilmaydi —
faqat jurnalga yoziladi.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from . import config as cfg

logger = logging.getLogger(__name__)

# Bosqichlar — UI shu raqamlarga qarab matn ko'rsatadi
CHECKING, DOWNLOADING, READY, FAILED = "checking", "downloading", "ready", "failed"


def is_frozen() -> bool:
    """PyInstaller exe ichida ishlayapmizmi."""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def install_root() -> Path:
    """O'rnatilgan dastur papkasi (exe + _internal shu yerda)."""
    return current_exe().parent


def update_dir() -> Path:
    path = cfg.config_dir() / "update"
    path.mkdir(parents=True, exist_ok=True)
    return path


def staged_path(version: str) -> Path:
    return update_dir() / f"SevimliKassa-{version}.zip"


def run_flag() -> Path:
    """Sog'liq bayrog'i — yangi versiya ishga tushganini bildiradi.

    Yangilash skripti bu faylni o'chiradi, so'ng yangi exe'ni ochadi.
    Yangi exe ishga tushsa `mark_started()` uni qayta yaratadi. Skript
    belgilangan vaqt ichida fayl paydo bo'lmasa — yangilanish yiqilgan
    deб zaxiradan tiklaydi (rollback).
    """
    return update_dir() / "run-ok"


def backup_dir() -> Path:
    return update_dir() / "backup"


def mark_started() -> None:
    """Dastur muvaffaqiyatli ishga tushdi — sog'liq bayrog'ini yozamiz.

    Bu `main()` boshida chaqiriladi: shu nuqtaga yetganimiz — exe ochildi
    va Python (python3xx.dll) yuklandi degani. Aynan shu narsa buzuq
    yangilanishlarda yiqilardi. Arzon amal; xato bo'lsa ham dastur ishlar.
    """
    try:
        from .version import VERSION
        run_flag().write_text(VERSION, encoding="utf-8")
    except Exception:
        pass


def cleanup(keep: str = "") -> None:
    """Eski yuklab olingan fayl va papkalarni tozalaydi — disk to'lmasin."""
    import shutil

    try:
        for f in update_dir().glob("SevimliKassa-*.zip*"):
            if keep and f.name.startswith(f"SevimliKassa-{keep}.zip"):
                continue
            f.unlink(missing_ok=True)
        for d in update_dir().glob("new-*"):
            if d.is_dir() and not (keep and d.name == f"new-{keep}"):
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


# Papkani almashtirish skripti — ZAXIRA va ROLLBACK bilan.
#   NEW    — ochilgan yangi dastur papkasi (SevimliKassa.exe + _internal)
#   TARGET — o'rnatilgan dastur papkasi (hozir ishlab turgan)
#   EXE    — TARGET\SevimliKassa.exe
#   BACKUP — joriy o'rnatmaning zaxira nusxasi (rollback uchun)
#   FLAG   — sog'liq bayrog'i (yangi versiya ishga tushsa yozadi)
#
# Bosqichlar:
#   1) TARGET zaxiraga nusxalanadi (o'qish qulf bilan ham ishlaydi).
#   2) FLAG o'chiriladi.
#   3) Ilova chiqib, exe bo'shaguncha kutib, NEW ustiga ko'chiriladi (robocopy).
#   4) Yangi exe ochiladi.
#   5) 20 s ichida FLAG paydo bo'lsa — muvaffaqiyat (yangi versiya ishga tushdi).
#      Aks holda — yangilanish yiqilgan, BACKUP dan tiklanadi (ROLLBACK) va
#      eski versiya qayta ochiladi.
# robocopy chiqish kodi 8 dan kichik bo'lsa — muvaffaqiyat.
_BAT = r"""@echo off
chcp 65001 >nul
set "NEW={new}"
set "TARGET={target}"
set "EXE={exe}"
set "BACKUP={backup}"
set "FLAG={flag}"

rem --- 1) Joriy o'rnatmani zaxiraga (rollback uchun). O'qish qulf bilan ham OK.
rd /s /q "%BACKUP%" >nul 2>&1
robocopy "%TARGET%" "%BACKUP%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul

rem --- 2) Sog'liq bayrog'ini o'chiramiz (yangi versiya uni qayta yaratadi)
del "%FLAG%" >nul 2>&1

rem --- 3) Ilova chiqib, exe bo'shaguncha kutamiz va yangisini ko'chiramiz
set /a n=0
:wait
timeout /t 1 /nobreak >nul
robocopy "%NEW%" "%TARGET%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 (
  set /a n+=1
  if %n% lss 60 goto wait
)

rem --- 4) Yangi versiyani ochamiz
timeout /t 2 /nobreak >nul
start "" "%EXE%"

rem --- 5) Sog'liq tekshiruvi: 20 s ichida FLAG paydo bo'lsa — muvaffaqiyat
set /a m=0
:health
timeout /t 1 /nobreak >nul
if exist "%FLAG%" goto ok
set /a m+=1
if %m% lss 20 goto health

rem --- Yangi versiya ishga tushmadi -> ROLLBACK: zaxiradan tiklaymiz
robocopy "%BACKUP%" "%TARGET%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
start "" "%EXE%"

:ok
rd /s /q "%NEW%" >nul 2>&1
rd /s /q "%BACKUP%" >nul 2>&1
del "%~f0" >nul 2>&1
"""


def _extract(zip_path: Path, version: str) -> Path | None:
    """ZIP ni ochadi va ichidagi dastur papkasini (SevimliKassa.exe bor
    papka) qaytaradi. Ichi to'liq bo'lmasa — None.

    ZIP tuzilishi: `SevimliKassa/SevimliKassa.exe`, `SevimliKassa/_internal/…`.
    Ba'zan qadoqlashda bir qavat ortiqcha/kam bo'lishi mumkin, shuning
    uchun SevimliKassa.exe ni ichkaridan qidiramiz.
    """
    import shutil

    dest = update_dir() / f"new-{version}"
    shutil.rmtree(dest, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
    except (zipfile.BadZipFile, OSError) as e:
        logger.error("ZIP ochilmadi: %s", e)
        return None

    for exe in dest.rglob("SevimliKassa.exe"):
        root = exe.parent
        # python312* — dastur yuragi. Yo'q bo'lsa papka chala, o'rnatmaymiz.
        has_py = any(root.glob("_internal/python3*.dll")) or any(
            root.glob("python3*.dll")
        )
        if has_py:
            return root
        logger.error("Ochilgan papkada python3xx.dll yo'q: %s", root)
        return None
    logger.error("Ochilgan ZIP ichida SevimliKassa.exe topilmadi")
    return None


def apply(zip_path: Path) -> bool:
    """Yangi dastur ZIP'ini ochib, o'rnatilgan papka ustiga ko'chiradi va
    ilovani qayta ochadi.

    True qaytarsa — chaqiruvchi ilovani DARHOL yopishi kerak (skript
    kutib turibdi). False — yig'ilmagan muhit yoki xato; hech narsa
    o'zgarmagan.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        logger.error("Yangilanish fayli topilmadi: %s", zip_path)
        return False

    if not is_frozen() or os.name != "nt":
        logger.warning(
            "Yig'ilmagan muhit — o'zini almashtirish o'tkazib yuborildi (%s)",
            zip_path,
        )
        return False

    version = zip_path.stem.replace("SevimliKassa-", "") or "yangi"
    new_dir = _extract(zip_path, version)
    if new_dir is None:
        return False

    target = install_root()
    exe = target / "SevimliKassa.exe"
    bat = update_dir() / "apply-update.bat"
    bat.write_text(
        _BAT.format(
            new=str(new_dir),
            target=str(target),
            exe=str(exe),
            backup=str(backup_dir()),
            flag=str(run_flag()),
        ),
        encoding="utf-8",
    )

    creation = 0
    creation |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    creation |= getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat)],
            creationflags=creation,
            close_fds=True,
            cwd=str(target),
        )
    except OSError as e:
        logger.error("Yangilash skripti ishga tushmadi: %s", e)
        return False

    logger.info("Yangilash skripti ishga tushdi: %s → %s", new_dir, target)
    return True

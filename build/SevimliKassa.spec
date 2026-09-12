# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller yig'ish sozlamasi.

Natija: `dist/SevimliKassa/` PAPKASI — ichida SevimliKassa.exe va yonida
`_internal/` (python312.dll va boshqa kutubxonalar). Kassaga Python
o'rnatish shart emas.

NEGA PAPKA (onedir), bitta fayl (onefile) EMAS:
    Onefile exe har ochilganda ichidagi Python'ni vaqtinchalik `Temp`
    papkaga chiqaradi va o'sha yerdan yuklaydi. Bu ikki jiddiy muammo
    tug'dirar edi:
      1) Antivirus chiqarilayotgan `python312.dll` ni «shubhali» deb
         o'chirib tashlar, dastur «python312.dll topilmadi» bilan
         yiqilardi.
      2) Temp to'lib qolsa yoki tozalansa — o'sha xato.
    Onedir'da hech narsa Temp'ga chiqmaydi: python312.dll exe yonida
    doimiy turadi, bir marta tekshiriladi, joyidan qimirlamaydi. Shu
    bilan har ikki muammo ildizidan yo'qoladi. Ishga tushish ham tezroq.

Yig'ish (Windows'da) — EXE-YASASH.bat buni o'zi qiladi:
    pyinstaller build/SevimliKassa.spec --noconfirm --clean
Natija: dist/SevimliKassa/  (keyin EXE-YASASH.bat uni dist/SevimliKassa.zip
ga qadoqlaydi — panelga yuklash va tarqatish uchun).
"""

import glob
import os

from PyInstaller.utils.hooks import collect_submodules

# --- Universal C Runtime (UCRT) ------------------------------------------
# Eski Windows'da (7/8.1, eski Windows 10) UCRT OS ichida bo'lmaydi.
# Ilova ochilishi uchun `ucrtbase.dll` va `api-ms-win-*.dll` fayllari
# yonida bo'lishi shart — aks holda "bu ilova mos emas" xatosi chiqadi.
# Bu fayllar build/ucrt/ ichida saqlanadi va har build ichiga qo'shiladi.
# (Ba'zi Python o'rnatmalari ularni o'zi bermaydi — shuning uchun qadadik.)
_UCRT_DIR = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "ucrt")
_UCRT_BINS = [(p, ".") for p in glob.glob(os.path.join(_UCRT_DIR, "*.dll"))]

# Qt'ning keraksiz qismlari EXE hajmini bekorga oshiradi — chiqarib
# tashlaymiz. Kassada brauzer ham, 3D ham, multimedia ham kerak emas.
EXCLUDE = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "tkinter", "matplotlib", "numpy", "PIL",
]

a = Analysis(
    # Kirish nuqtasi — launcher (pos'ni paket sifatida yuklaydi).
    # To'g'ridan-to'g'ri pos/main.py bersak, nisbiy importlar buziladi.
    ["../pos_launcher.py"],
    pathex=[".."],
    # UCRT DLL'lari — (manba, joy) juftliklari. Analysis ularni to'g'ri
    # normallashtiradi va _internal ichiga qo'yadi.
    binaries=_UCRT_BINS,
    datas=[
        ("../pos/sevimli-kassa.ico", "pos"),
        ("../pos/sevimli-logo.png", "pos"),
        # Inter shriftlari (pos/fonts/ ichida .ttf bo'lsa) — UI shrifti
        ("../pos/fonts", "pos/fonts"),
    ],
    # `shared` — chek matnini yig'adigan modul (pos/main.py ishlatadi).
    # Onedir ichiga kirishi uchun uni ham qo'shamiz.
    # `shared` — chek matni; `win32*` — printerga to'g'ridan-to'g'ri (RAW
    # ESC/POS) chop etish uchun (pywin32). Onedir ichiga kirishi shart.
    hiddenimports=(
        collect_submodules("pos")
        + collect_submodules("shared")
        + ["win32print", "win32api", "pywintypes"]
        # QtSvg — UI ikonalari (pos/ui/icons.py) shu bilan chiziladi.
        # Aniq ko'rsatamiz: build'da tushib qolsa, ikonali ekranlar yiqiladi.
        + ["PySide6.QtSvg"]
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDE,
    noarchive=False,
)

pyz = PYZ(a.pure)

# onedir: EXE ichiga faqat dastur kodi kiradi, kutubxonalar (DLL'lar)
# esa COLLECT bilan yonidagi `_internal/` papkaga qo'yiladi —
# `exclude_binaries=True` shuni bildiradi.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SevimliKassa",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Kassada qora konsol oynasi ochilmasin
    console=False,
    icon="../pos/sevimli-kassa.ico",
)

coll = COLLECT(
    exe,
    a.binaries,          # UCRT ham shu ichida (Analysis'ga berilgan)
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SevimliKassa",
)

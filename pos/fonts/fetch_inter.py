"""
Inter shriftini (4 vazn) rasmiy manbadan shu papkaga yuklab oladi.

Ishlatish (internet bor mashinada):
    python pos/fonts/fetch_inter.py

Inter — SIL Open Font License (bepul). Fayllar bo'lgach, dastur ochilишида
avtomatik yuklanadi va UI Inter'da ko'rinadi. Yuklab bo'lmasa — dastur
Segoe UI'ga o'tadi (Windows'da bor), UI baribir professional ko'rinadi.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# rsms/inter v4.0 — hosted font-files (OFL). Bir manba ishlamasa,
# ikkinchisiga o'tadi.
STYLES = ["Regular", "Medium", "SemiBold", "Bold"]
SOURCES = [
    "https://github.com/rsms/inter/raw/v4.0/docs/font-files/Inter-{s}.ttf",
    "https://cdn.jsdelivr.net/gh/rsms/inter@v4.0/docs/font-files/Inter-{s}.ttf",
]


def fetch_one(style: str) -> bool:
    dest = HERE / f"Inter-{style}.ttf"
    if dest.exists() and dest.stat().st_size > 50_000:
        print(f"  bor: {dest.name}")
        return True
    for tmpl in SOURCES:
        url = tmpl.format(s=style)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 50_000:
                continue
            dest.write_bytes(data)
            print(f"  yuklandi: {dest.name} ({len(data)//1024} KB)")
            return True
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    print(f"  XATO: {style} yuklab bo'lmadi ({last})")
    return False


def main() -> int:
    print("Inter shriftini yuklab olish...")
    ok = all(fetch_one(s) for s in STYLES)
    if ok:
        print("Tayyor. Endi EXE yig'ilganда Inter ichiga qo'shiladi.")
        return 0
    print("Ba'zi fayllar yuklanmadi. Qo'lda qo'shing (README.md ga qarang).")
    return 1


if __name__ == "__main__":
    sys.exit(main())

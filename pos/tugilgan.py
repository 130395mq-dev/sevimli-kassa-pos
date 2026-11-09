"""Mijozning tug'ilgan kuni — kassa tomoni (SEVIMLI BONUS, egasi 2026-11-08).

Karta urilganda server mijoz bilan birga `birthday` («12.05» yoki
«12.05.1990») va `is_birthday` (bugunmi — server sanasi bo'yicha) yuboradi.
Kassa:
  * tug'ilgan kuni bo'lsa — ekranda katta belgi, kassir og'zaki tabriklaydi,
    chekda tabrik so'zi chiqadi (sovg'a ball YO'Q — egasining qarori);
  * tug'ilgan kuni kiritilmagan bo'lsa — kassirga «kiriting» oynasi chiqadi,
    kassir mijozdan so'rab shu yerda kiritadi yoki «Keyinroq» deydi.

Sana tekshiruvi serverda ham bor (catalog/tugilgan_kun.py) — bu yerdagi
tekshiruv kassirga xatoni darhol ko'rsatish uchun.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from .i18n import tr

_RE = re.compile(r"^\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*(\d{2}|\d{4}))?\s*$")


class BirthdayError(ValueError):
    """Kassirga ko'rsatiladigan xato matni."""


def normalize(text: str, today: date | None = None) -> str:
    """Kassir yozganini tekshirib, «KK.OO» yoki «KK.OO.YYYY» qaytaradi."""
    m = _RE.match(text or "")
    if not m:
        raise BirthdayError(tr("Sana «KK.OO» yoki «KK.OO.YYYY» ko'rinishida bo'lsin, masalan 12.05"))
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else None
    today = today or date.today()
    if year is not None and year < 100:
        year = 2000 + year if 2000 + year <= today.year else 1900 + year
    if not 1 <= month <= 12:
        raise BirthdayError(tr("Oy 1 dan 12 gacha bo'lishi kerak"))
    max_day = calendar.monthrange(year, month)[1] if year else (29 if month == 2 else calendar.monthrange(2001, month)[1])
    if not 1 <= day <= max_day:
        raise BirthdayError(tr("Bu oyda {d}-kun yo'q").format(d=day))
    if year is not None and (year < 1900 or date(year, month, day) > today):
        raise BirthdayError(tr("Yil noto'g'ri"))
    base = f"{day:02d}.{month:02d}"
    return f"{base}.{year}" if year else base


def greeting_name(name: str) -> str:
    """Chek va ekran uchun ism: bosh harflar bilan. Ism bazada
    «Familiya Ism» yoki hohlagan ko'rinishda — o'zgartirmaymiz."""
    return " ".join((name or "").split()).upper()

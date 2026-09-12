"""
Kompyuterning o'z belgisi — «bir login bir vaqtda bitta kassada» uchun.

Server kassir kirganda loginni shu belgiga biriktiradi. Boshqa kompyuter
o'sha login bilan kirmoqchi bo'lsa, server uni taniydi va rad etadi.

Belgi bir marta yaratiladi va `%APPDATA%\\SevimliKassa\\device.txt` da
turadi: dastur yangilansa ham, qayta o'rnatilsa ham o'zgarmaydi (config
papkasi saqlanadi). Tasodifiy UUID — kompyuterning apparat ma'lumotlari
o'qilmaydi, shaxsiy hech narsa serverga ketmaydi. Nomi (`platform.node`)
faqat panelda «qaysi kompyuter» deb ko'rsatish uchun.
"""

from __future__ import annotations

import platform
import uuid

from . import config as cfg

_cached: dict[str, str] = {}


def device_id() -> str:
    """Barqaror qurilma belgisi (36 belgi). Fayl bo'lmasa — yaratiladi."""
    if "id" in _cached:
        return _cached["id"]
    file = cfg.config_dir() / "device.txt"
    value = ""
    try:
        value = file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    if not value or len(value) < 8:
        value = str(uuid.uuid4())
        try:
            file.write_text(value, encoding="utf-8")
        except OSError:
            # Yozib bo'lmasa ham ishlaymiz — faqat keyingi ochilishda belgi
            # boshqa bo'ladi (server jim qolgan eskisini 3 daqiqada bo'shatadi)
            pass
    _cached["id"] = value[:64]
    return _cached["id"]


def device_name() -> str:
    """Kompyuter nomi — panelda ko'rsatish uchun (masalan DESKTOP-7K2)."""
    if "name" in _cached:
        return _cached["name"]
    try:
        name = platform.node() or ""
    except Exception:
        name = ""
    # Sarlavhaga faqat ASCII sig'adi — begona belgilarni tashlaymiz
    name = name.encode("ascii", "ignore").decode("ascii").strip()[:64]
    _cached["name"] = name or "kompyuter"
    return _cached["name"]

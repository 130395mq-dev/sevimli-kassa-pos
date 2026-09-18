"""
Kassa sozlamalari.

Fayl Windows'da `%APPDATA%\\SevimliKassa\\config.json` da turadi.
Token shu yerda saqlanadi — kodda emas, EXE ichida emas.

Birinchi ishga tushirishda fayl yaratiladi va kassir server manzili bilan
tokenni kiritadi. Ular Hub'ning admin panelidan olinadi.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = Path(base) / "SevimliKassa"
    path.mkdir(parents=True, exist_ok=True)
    return path


#: Sevimli Market serveri. Kassada so'ralmaydi — dasturning ichida.
#: Boshqa serverga ulash kerak bo'lsa: config.json'dagi server_url yoki
#: SEVIMLI_SERVER muhit o'zgaruvchisi.
DEFAULT_SERVER = os.environ.get(
    "SEVIMLI_SERVER", "https://hub-production-0882.up.railway.app"
)


@dataclass
class Config:
    server_url: str = DEFAULT_SERVER
    token: str = ""
    #: Chek chiqadigan printer nomi (Windows'dagi aniq nomi). Bo'sh bo'lsa —
    #: Windows'ning asosiy printeri ishlatiladi.
    printer: str = ""
    #: Qog'oz kengligi: "80" (80mm, 48 belgi) yoki "58" (58mm, 32 belgi)
    paper: str = "80"
    #: Har savdodan keyin chek avtomatik chiqsinmi
    auto_print: bool = True
    #: ESC/POS kod sahifasi raqami (ESC t n). 17 = PC866 (kirill).
    #: Printer boshqacha kutsa shu yerda o'zgartiriladi — qayta yig'ish shart emas.
    printer_codepage: int = 17
    #: Chek matni shu kodlash bilan yuboriladi (kod sahifasiga mos bo'lishi kerak)
    printer_encoding: str = "cp866"
    #: Interfeys tili: "uz" yoki "ru"
    language: str = "uz"
    #: Katalogni qayta so'rash oralig'i, sekundda (farq so'rovi arzon —
    #: o'zgarish bo'lmasa bo'sh javob keladi)
    catalog_interval: int = 120
    #: Navbatni yuborishga urinish oralig'i, sekundda
    outbox_interval: int = 20
    #: Bo'sh kassa oynasidagi jonli supermarket foni. Juda zaif
    #: kompyuterda false qilib qo'yish mumkin (statik fon bo'ladi).
    animated_bg: bool = False

    @property
    def receipt_width(self) -> int:
        """Chek kengligi (belgi soni) — qog'oz o'lchamiga qarab."""
        return 32 if str(self.paper) == "58" else 48

    @property
    def is_ready(self) -> bool:
        return bool(self.server_url and self.token)

    @property
    def base(self) -> str:
        return (self.server_url or DEFAULT_SERVER).rstrip("/")


def path() -> Path:
    return config_dir() / "config.json"


def load() -> Config:
    file = path()
    if not file.exists():
        return Config()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return Config()
    known = {f for f in Config.__dataclass_fields__}
    return Config(**{k: v for k, v in data.items() if k in known})


def save(config: Config) -> None:
    path().write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8"
    )

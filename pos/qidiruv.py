"""
Tovar qidiruvi: nomni va so'rovni bitta «kalit»ga keltirish.

Kassir tovar nomini aniq yozmaydi — va yozmasligi ham kerak:

  * nomlar MoySklad'da kirillcha/ruscha («Сут 1 литр», «Гўшт мол»),
    kassir esa lotincha teradi («sut», «gosht») — yoki aksincha;
  * katta-kichik harf farqi bo'lmasligi kerak (SQLite LIKE kirillchada
    katta-kichikni FARQLAYDI — «сут» «Сут»ni topmasdi);
  * so'zlar boshqa tartibda yoki qismi yoziladi («1 litr sut», «sut lit»);
  * apostrof, tire, o'xshash harflar (q/k, x/h, c/k) adashtirmasin.

Yechim: nom ham, so'rov ham `key()` orqali bir xil ko'rinishga keltiriladi
(lotin, kichik harf, apostrofsiz, o'xshash harflar birlashtirilgan), keyin
so'rovning HAR BIR so'zi nom kalitida uchrasa — tovar topiladi.

    key("Гўшт мол (вазнли)")  -> "gosht mol vaznli"
    key("Go'sht")             -> "gosht"
    key("Coca-Cola 1,5л")     -> "koka kola 1.5l"
"""

from __future__ import annotations

import re

# Kirill → lotin (o'zbek kirillchasi + ruscha). Kichik harflar uchun;
# matn avval .lower() qilinadi.
_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # o'zbek kirillchasi
    "ў": "o", "қ": "k", "ғ": "g", "ҳ": "h",
    # ukraincha/qozoqcha harflar ba'zan nomlarga kirib qoladi
    "і": "i", "ї": "i", "є": "e", "ә": "a", "ң": "n", "ү": "u", "ұ": "u",
}

# Lotin apostrof turlari (o', g', oʻ, o‘, o’) — hammasi tashlanadi
_APOS = "'’‘ʻʼ`´"

# O'xshash lotin harflari — bitta ko'rinishga (nomda ham, so'rovda ham)
_FOLD = [
    ("ch", "ch"),   # avval o'zini saqlab qo'yamiz (c → k dan himoya)
    ("q", "k"),
    ("x", "h"),
    ("w", "v"),
]

_NON_WORD = re.compile(r"[^0-9a-z.\s]+")
_SPACES = re.compile(r"\s+")


def key(text: str) -> str:
    """Matn → qidiruv kaliti (lotin, kichik harf, toza)."""
    s = (text or "").lower()
    for ch in _APOS:
        s = s.replace(ch, "")
    s = "".join(_CYR.get(ch, ch) for ch in s)
    # Vergul raqamlarda kasr belgisi: "1,5" va "1.5" bir xil
    s = s.replace(",", ".")
    # c → k, lekin "ch" o'z holicha (chip, choy)
    s = re.sub(r"c(?!h)", "k", s)
    s = s.replace("q", "k").replace("x", "h").replace("w", "v")
    # Qolgan belgilar (tire, qavs, %, № …) — bo'shliq
    s = _NON_WORD.sub(" ", s)
    # Yolg'iz nuqta (raqamlar orasida bo'lmagan) — bo'shliq
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    return _SPACES.sub(" ", s).strip()


def tokens(query: str) -> list[str]:
    """So'rov so'zlari (kalit ko'rinishida). Bo'sh so'rov → []."""
    return [t for t in key(query).split(" ") if t]


def matches(name_key: str, query: str) -> bool:
    """Nom kaliti so'rovning hamma so'zlarini o'z ichiga oladimi."""
    toks = tokens(query)
    return bool(toks) and all(t in name_key for t in toks)


def rank(name_key: str, query: str) -> int:
    """Tartiblash uchun: 0 — nom so'rov bilan boshlanadi, 1 — biror so'z
    so'rovning birinchi so'zi bilan boshlanadi, 2 — shunchaki ichida bor."""
    q = key(query)
    toks = q.split(" ")
    if not q:
        return 2
    if name_key.startswith(q):
        return 0
    first = toks[0]
    if any(w.startswith(first) for w in name_key.split(" ")):
        return 1
    return 2

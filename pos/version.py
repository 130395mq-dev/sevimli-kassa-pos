"""
Kassa ilovasining versiyasi.

Har yangi chiqarishda shu raqam oshiriladi (1.1.0 → 1.2.0), keyin
KASSA-EXE-YASASH bilan exe yig'iladi va panelning «Versiyalar» sahifasiga
yuklanadi. Kassalar shu raqamni serverdagi bilan solishtirib, kichik bo'lsa
o'zini yangilaydi.

Format: KATTA.O'RTA.KICHIK — raqamlar bo'yicha solishtiriladi
(1.10.0 > 1.9.0), matn bo'yicha emas.
"""

VERSION = "1.18.2"


def version_key(version: str) -> tuple[int, ...]:
    """«1.2.10» → (1, 2, 10). Raqam bo'lmagan qism 0 deb olinadi."""
    parts = []
    for chunk in (version or "").strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return version_key(candidate) > version_key(current)

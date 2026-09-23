"""SEVIMLI — daylight palette for long cashier shifts."""
BG_BASE = "#F3F5F4"
BG = "#FFFFFF"
BG_SOFT = "#F0F4F2"
BG_PAGE = BG_BASE
SURFACE_DARK = "#F7F9F8"
SURFACE_2 = "#E5EDE8"
PRIMARY_DARK = "#103D32"
DARK = "#103D32"
ACCENT = "#18724F"
ACCENT_DARK = "#10593C"
ACCENT_SOFT = "#53836D"
ACCENT_PALE = "#E8F4ED"
ACCENT_GLOW = "#25845D"
PRICE = "#12603F"
INK = "#172D25"
INK_SOFT = "#3E574C"
MUTED = "#63776D"
FAINT = "#728379"
ON_ACCENT = "#FFFFFF"
LINE = "#DFE7E2"
LINE_STRONG = "#BDCEC3"
OK = "#17754D"
DANGER = "#BD3C3C"
WARN = "#966015"
AURORA_1 = BG_BASE
AURORA_2 = BG_BASE
AURORA_3 = BG_BASE
GLOW = BG_BASE
FONT_FAMILY = "Inter"
FONT_FALLBACK = ["Segoe UI", "Arial", "sans-serif"]
FONT = "Inter, 'Segoe UI', Arial, sans-serif"
FS_DISPLAY = 36
FS_TITLE = 22
FS_H2 = 18
FS_BODY = 15
FS_SMALL = 13
FS_TINY = 11
CATALOG_WIDTH = 486
RECEIPT_WIDTH = 500      # keng ekranda (1280+); torroq ekranda receipt_width()
RECEIPT_MIN = 410        # ilgarigi doimiy kenglik — undan tor bo'lmaydi
CATALOG_MIN = 520        # 3 ustun karta (3×156 + 16) + skrollbar 20 + chetlar


def receipt_width(screen_w: int) -> int:
    """Chek paneli kengligi ekranga qarab.

    Kassa ekranlari har xil: 4:3 (1024×768) va keng (1366×768, 1280×1024).
    Keng ekranda 500 px; 1024 da esa katalogga kamida 3 ustun karta
    (CATALOG_MIN) qolishi kerak — qolgani chekka. 410 dan tor bo'lmaydi.
    """
    free = screen_w - 2 * 14 - 14 - CATALOG_MIN   # body chetlari + oraliq
    return max(RECEIPT_MIN, min(RECEIPT_WIDTH, free))
TOTAL_BAR_HEIGHT = 82
HEADER_HEIGHT = 72
HOTKEY_BAR_HEIGHT = 48
RADIUS = 14
RADIUS_SM = 8

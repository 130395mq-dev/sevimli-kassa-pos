"""
Sevimli Kassa — YAGONA design system (ranglar, tipografiya, o'lchamlar).

Butun POS shu tokenlardan foydalanadi. Rang to'g'ridan-to'g'ri yozilmaydi —
har doim `theme` orqali. Shu tufayli butun interfeys bir joydan boshqariladi.

TUN REJIMI (2026-09): fon — to'q grafit, biroz ko'kimtir. Chetlarda yumshoq
zumrad «shimol yog'dusi» (aurora) sekin harakatlanadi. Kartalar va tugmalar
yengil 3D: yumshoq soya, yuqori chetда yorug'lik, nozik gradient. Matnlar
aniq o'qiladi: nomlar oqish, narxlar och zumrad, izohlar och kulrang.

    #0C1618  BG_BASE       — fon asosi (aurora ustiga chiziladi)
    #16282C  BG            — karta / sirt (elevatsiya)
    #1FA968  ACCENT        — JAMI, tanlangan, tasdiq (zumrad)
    #57E0A2  PRICE         — narx (och zumrad)
    #EAF4EE  INK           — asosiy matn (oqish)

O'lcham va joylashuv O'ZGARMAYDI — faqat tashqi ko'rinish.
"""

# ── Fon / aurora ─────────────────────────────────────────────────────
#: Fon asosi — to'q grafit, biroz ko'kimtir.
BG_BASE  = "#0C1618"
#: «Shimol yog'dusi» ranglari — yumshoq zumrad yog'du (aurora dog'lari).
AURORA_1 = "#15E3A0"   # yorqin zumrad
AURORA_2 = "#0E8F7A"   # to'qroq ko'k-yashil
AURORA_3 = "#1C6FA6"   # nozik ko'kimtir urg'u (juda kam)
#: Logo ortidagi mayin yashil yorug'lik halqasi.
GLOW     = "#25C489"

# ── Sirtlar (to'q, elevatsiyali) ─────────────────────────────────────
BG           = "#16282C"   # karta / ro'yxat foni (fon asosidan ochroq)
BG_SOFT      = "#1E353A"    # yumshoq sirt / ikkilamchi tugma
BG_PAGE      = BG_BASE      # sahifa foni (aurora ko'rinadigan joylar)
SURFACE_DARK = "#0F2125"    # to'q sirt
SURFACE_2    = "#244744"    # bosilgan holat / ikkilamchi sirt

# ── Chrome — header va pastki panel ──────────────────────────────────
PRIMARY_DARK = "#0A1416"
DARK         = "#0C181A"    # header / pastki chrome (fonda erib turadi)

# ── Accent (zumrad) ──────────────────────────────────────────────────
ACCENT       = "#1FA968"    # JAMI, tanlangan element, tasdiqlash
ACCENT_DARK  = "#17824F"    # bosilgan holat (to'qroq zumrad)
ACCENT_SOFT  = "#6FC49E"    # ikkilamchi urg'u / muted yashil
ACCENT_PALE  = "#1B3A31"    # tanlangan qator foni (to'q zumrad tus)
ACCENT_GLOW  = "#2FD68F"    # yorqin urg'u (3D yorug'lik cheti)
PRICE        = "#57E0A2"    # narx — och zumrad

# ── Matn ─────────────────────────────────────────────────────────────
INK          = "#EAF4EE"    # asosiy matn / nomlar (oqish)
INK_SOFT     = "#C4DBCF"    # ikkilamchi matn
MUTED        = "#8FAEA1"    # izohlar (och kulrang-yashil)
FAINT        = "#6C877B"    # yorliqlar
ON_ACCENT    = "#F2FFF8"    # zumrad ustidagi matn (JAMI, tugma)

# ── Chiziqlar ────────────────────────────────────────────────────────
LINE         = "#26403F"    # ajratgichlar (to'q)
LINE_STRONG  = "#37544F"    # chegaralar

# ── Holat ranglari — to'q fonda aniq ko'rinsin ──────────────────────
OK           = "#33C07E"    # muvaffaqiyat
DANGER       = "#E86B62"    # xato (to'q fonda yorqinroq)
WARN         = "#E0A44A"    # ogohlantirish / ulgurji narx

# ── Tipografiya ──────────────────────────────────────────────────────
# Birlamchi: Inter (ilova ichida yuklanadi, pos/fonts/). Bo'lmasa —
# Segoe UI (barcha Windows'da bor). Butun UI shu oiladan.
FONT_FAMILY  = "Inter"
FONT_FALLBACK = ["Segoe UI", "Arial", "sans-serif"]
FONT         = "Inter, 'Segoe UI', Arial, sans-serif"

# Tipografiya shkalasi (piksel) — barcha ekranlar shundan foydalansin
FS_DISPLAY   = 32   # katta summalar
FS_TITLE     = 20   # sarlavha
FS_H2        = 17   # kichik sarlavha / tugma
FS_BODY      = 15   # asosiy matn
FS_SMALL     = 13   # izoh
FS_TINY      = 11   # yorliq

# ── O'lchamlar (O'ZGARMAYDI — joylashuv/bosiladigan hudud saqlanadi) ──
CATALOG_WIDTH    = 486   # (eski — endi grid cho'ziladi, min kenglik sifatida)
RECEIPT_WIDTH    = 470    # o'ng chek paneli — qat'iy kenglik (rail)
CATALOG_MIN      = 620    # grid paneli hech qachon shundan tor bo'lmaydi
TOTAL_BAR_HEIGHT = 76
HEADER_HEIGHT    = 56
HOTKEY_BAR_HEIGHT = 44
RADIUS           = 12   # standart burchak radiusi
RADIUS_SM        = 8

# Sevimli Kassa — POS terminal

Sevimli Market do'konlari uchun **kassa terminali** — Windows 10/11 x64 uchun
mustaqil dastur (PySide6). MoySklad Kassa o'rniga.

POS bazaga (PostgreSQL) yoki MoySklad'ga **to'g'ridan-to'g'ri ulanmaydi** —
faqat backend (`sevimli-kassa-backend`) bilan **HTTPS API** orqali ishlaydi.
Internet yo'q bo'lsa ham savdo qiladi (offline), internet qaytganda o'zi
sinxronlaydi.

```
POS  →  SQLite (offline navbat)  →  internet qaytganda  →  Backend API  →  PostgreSQL / MoySklad
```

## Imkoniyatlari

- Kassir login, tovar katalogi, qidiruv, shtrix-kod skaner
- Savat, miqdor, chegirma, mijoz, bonus
- Naqd / karta / aralash to'lov, qaytim
- **Chek chop etish** — to'g'ridan-to'g'ri (RAW ESC/POS) 80/58 mm termal printerga
- **Offline rejim** — lokal SQLite + outbox navbat, avtomatik sinxron (idempotent)
- **Avtomatik yangilanish** — paneldagi «Versiyalar» dan (fleshka kerak emas);
  yangilanishdan keyin kassir kirgan holida qoladi, smena yopilmaydi
- **Aloqa chiroqlari** — pastki qatorda `● Server ● MoySklad`
  (yashil / sariq / qizil, `pos/ui/link_lights.py`)
- **Panel sozlamalari 15 soniyada** — to'lov turlari, chegirma chegarasi,
  narx turlari paneldan o'zgarsa kassa qayta ochilmasdan qo'llaydi

## Struktura

| Yo'l | Vazifasi |
|------|----------|
| `pos/` | Dastur mantig'i (main, hub, cart, store, printer, updater...) |
| `pos/ui/` | Ekranlar (PySide6) — asosiy oyna, dialoglar, login, to'lov |
| `pos/ui/theme.py` | **Yagona design system** — ranglar, tipografiya, o'lchamlar |
| `pos/fonts/` | Inter shriftlari (ixtiyoriy, .ttf) |
| `shared/` | Chek matnini yig'uvchi modul (backend bilan umumiy nusxa) |
| `build/SevimliKassa.spec` | PyInstaller sozlamasi (onedir) |

## Ishga tushirish (dev)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pos.main
```

Birinchi ochilishda server manzili va kassa tokeni so'raladi (paneldan olinadi).

## Design system

Butun UI bitta joydan — `pos/ui/theme.py` — boshqariladi. Rang to'g'ridan-to'g'ri
yozilmaydi, har doim token orqali (`theme.ACCENT`, `theme.BG` ...).

Palitra (yashil): `#051F20 #0B2B26 #163832 #235347 #8EB69B #DAF1DE` + oq.
Shrift: **Inter** (`pos/fonts/` ichida .ttf bo'lsa), bo'lmasa **Segoe UI**.

## Build (Windows x64 EXE)

Natija — **papka** (onedir): `dist/SevimliKassa/` (ichida `SevimliKassa.exe` +
`_internal/`). Onefile emas — antivirus muammosi va Temp'ga chiqarish yo'q.

```bat
pip install -r requirements.txt pyinstaller==6.11.1
pyinstaller build\SevimliKassa.spec --noconfirm --clean
powershell Compress-Archive -Path dist\SevimliKassa -DestinationPath dist\SevimliKassa.zip -Force
```

Asosiy yo'l — GitHub Actions (pastda); lokal yig'ish faqat zaxira.

> **Muhim:** har doim **butun `SevimliKassa` papkasini** (yoki ZIP'ni) ko'chiring,
> yakka `.exe` faylni emas — u ishlamaydi.

## Yangi versiya chiqarish — GitHub yig'adi

Kompyuterda hech narsa yig'ilmaydi. `pos/version.py` dagi raqam oshiriladi,
ish stolidagi **`KASSA-GITHUBGA-YUKLASH.bat`** (→ `kassa_github_yukla.ps1`,
`-Auto` bilan savolsiz) kodni `130395mq-dev/sevimli-kassa-pos` repo'siga push
qiladi. GitHub Actions (`.github/workflows/build.yml`): Linux'da testlar →
Windows'da PyInstaller onedir → ZIP → GitHub Release `v<versiya>` (teg avval
bo'lsa — yangilanmaydi, ogohlantirish). Server (hub) 10 daqiqada bir
Release'ga qaraydi va yangi ZIP'ni o'zi «Versiyalar» ga qo'shadi
(`sales/releases.py`) — hech qanday kalit kerak emas. Lokal yig'ish — zaxira.

## Avto yuklash — `C:\Sevimli` (`tools/`)

Egasining kompyuterida hech narsa bosilmaydi. `tools/ornatish.ps1` bir marta
ishga tushiriladi: `C:\Sevimli\PortableGit` (git), `C:\Sevimli\server`
(hub repo) va `C:\Sevimli\kassa` (shu repo) papkalarini yaratadi va
«Планировщик заданий» ga har 5 daqiqada `tools/avto_yuklash.ps1` ni qo'yadi.

`avto_yuklash.ps1` har safar, har ikki repo uchun:

1. papkadagi o'zgarishlarni commit qiladi (oxirgi fayl 2 daqiqa tinch
   turgan bo'lsa); kassada `pos/`, `shared/`, `build/` o'zgargan bo'lsa
   `pos/version.py` dagi kichik raqamni o'zi oshiradi (skript/hujjat
   o'zgarsa — oshirmaydi, bekorga EXE yig'ilmaydi);
2. GitHub'dan yangiliklarni oladi (`fetch` + `rebase -X theirs` — ikki tomon
   bir faylni o'zgartirgan bo'lsa kompyuterdagi nusxa ustun);
3. `push` qiladi — **`--force` hech qachon ishlatilmaydi**; birlashtirib
   bo'lmasa bekor qilib, `C:\Sevimli\avto_yuklash.log` ga yozadi va
   keyingi safar qayta urinadi.

Shu tufayli GitHub'da (masalan, Claude sessiyasida) qilingan o'zgarishlar
kompyuterdagi papkaga ham o'zi tushadi. `PortableGit/`, `*.log`, `*.lock`
`.gitignore` da — repo'ga tushmaydi.

## Avtomatik yangilanish

1. Yangi versiya yig'iladi (`pos/version.py` dagi raqam oshiriladi).
2. `SevimliKassa.zip` panelga (**Versiyalar**) yuklanadi — qo'lda yoki
   `kassa_faqat_yukla.ps1` (maxfiy kalit bilan `POST /api/v1/release/upload`).
   Skript ZIP kod fayllaridan eski bo'lsa yuklamaydi («versiya mos emas»
   xatosining oldi olinadi).
3. Ishlab turgan kassa buni o'zi topadi (30 daqiqada bir), yuklab oladi,
   tekshiradi (SHA-256), eski nusxani zaxiralab, yangisini o'rnatadi va
   qayta ochilib **o'sha smena va ekranga qaytadi** (login so'ralmaydi).

Yangilanish paytida tugallanmagan savdo yoki sinxron navbat **yo'qolmaydi** —
lokal SQLite va outbox saqlanadi. Muvaffaqiyatsiz bo'lsa, eski versiyaga qaytadi.

## Shtrix-kod qoidalari (`pos/barcode.py`, `pos/hub.py`)

1. Avval kod katalogda **aynan** bormi — bo'lsa 1 dona. Tovarning barcha
   kodlari (`barcodes` jadvali) tekshiriladi.
2. Bo'lmasa — tarozi yorlig'imi: **29** + PLU(5) + gramm(5) + nazorat.
   `20…` kodlar tarozi emas (MoySklad o'zi yaratgan kodlar shunday
   boshlanadi). 50 kg dan og'ir yorliq va donali tovarga tushgan PLU
   sotilmaydi.

## Kirish va «bir login — bir kompyuter» (`pos/device.py`, `pos/hub.py`)

- Kassir bir marta login-parol bilan kiradi va **«Chiqish» bosilguncha**
  kirgan bo'lib qoladi (`kassa.db` → `login_session`): smena yopib-ochish,
  yangilanish, kompyuter qayta yoqilishi — parol so'ralmaydi. Smena yopiq
  bo'lsa kirish ekrani «SMENA OCHISH» rejimida ochiladi.
- Har so'rovda `X-Device` (bir marta yaratilgan UUID, `device.txt`) va
  `X-Device-Name` ketadi. Server loginni shu qurilmaga biriktiradi; boshqa
  kompyuter shu login bilan kirsa 409 → kirish ekranida sabab ko'rinadi
  (`HubBusyError`). Qayta ochilganda `session/resume` (parolsiz), «Chiqish» →
  `logout`. `hello` javobidagi `login_session`: `mine=False` — boshqa
  kompyuter kirib olgan, kassa kirish ekraniga qaytadi; `session` —
  uzaytirilgan token.

## Aralash to'lov (`pos/ui/split_payment.py`, `pos/cart.py`)

To'lov oynasidagi «ARALASH TO'LOV» tugmasi: har to'lov turiga summa,
«QOLGANINI», qoldi/qaytim. Hisob — `cart.split_payment` (karta chekdan
oshmaydi, ortiqcha naqd = qaytim, karta yopgan chekka naqd — xato).

## Chek printeri

Chek to'g'ridan-to'g'ri (RAW ESC/POS) tanlangan printerga yuboriladi —
Windows'ning "asosiy printer"iga bog'liq emas. Menyu → **Printer sozlamalari**:
printer tanlash, qog'oz o'lchami (80/58 mm), avto-chek, test chek.

> 80 mm termal printerlarda qog'oz o'lchami **80 mm** bo'lsin (A4 emas).

## Testlar

```bash
python -m pos.test_pos
python -m pos.test_store
python -m pos.test_update
python -m pos.test_links
python -m pos.test_split
python -m pos.test_session
python -m shared.test_receipt
```

## Windows qo'llab-quvvatlash

Faqat **Windows 10 x64** va **Windows 11 x64** uchun. Onedir build, `_internal/`
ichida Python — kassaga Python o'rnatish shart emas.

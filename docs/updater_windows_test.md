# Updater — Windows sinov rejasi

> **Halol eslatma.** Bu loyiha Linux muhitida yig'ildi. Yangilash mexanizmi
> Windows'ning `robocopy` va `.bat` buyruqlariga tayanadi — ularni Linux'da
> ishga tushirib bo'lmaydi. Shuning uchun bu yerdagi sinovlar **Windows
> mashinasida odam tomonidan** bajarilishi kerak. Quyida ikki xil sinov bor:
>
> 1. **Izolyatsiyalangan harness** (`updater_windows_test.ps1`) — `_BAT`
>    ichidagi papka-almashtirish, sog'liq-bayrog'i va **rollback** mantig'ini
>    xavfsiz, tashlab yuboriladigan papkalarda tekshiradi. Haqiqiy o'rnatmaga
>    tegmaydi. Bir necha soniyada natija beradi.
> 2. **To'liq oqim** (real in-app) — haqiqiy `SevimliKassa.exe` ni ikki
>    versiyada yig'ib, ilovaning o'zi yangilanishini kuzatish.
>
> Updater kodi (`pos/updater.py`) sinov uchun **o'zgartirilmagan**.

Linux'da nima allaqachon tekshirilgan (`python -m pos.test_update`):
- `_BAT` to'g'ri shakllanadi — NEW/TARGET/BACKUP/FLAG o'rinlari, robocopy,
  rollback bloki, `del "%~f0"` (o'zini o'chirish) mavjud;
- SHA-256 tekshiruvi (buzuq fayl qabul qilinmaydi);
- ZIP ichidagi papka tekshiruvi (`SevimliKassa.exe` + `python3xx.dll`);
- yig'ilmagan muhitda hech narsa almashtirilmaydi.

Windows'da tekshiriladigan narsa — aynan `robocopy` bilan real papka
almashtirilishi va rollback ishlashi.

---

## 1-sinov — izolyatsiyalangan harness (tavsiya etiladi, tez)

Windows mashinasida PowerShell'ni oching va POS papkasida:

```powershell
# Muvaffaqiyatli yangilanish (health flag paydo bo'ladi -> swap qoladi)
powershell -ExecutionPolicy Bypass -File docs\updater_windows_test.ps1 -Scenario ok

# Rollback (yangi versiya "ishga tushmaydi" -> BACKUP dan tiklanadi)
powershell -ExecutionPolicy Bypass -File docs\updater_windows_test.ps1 -Scenario rollback
```

Harness `_BAT` bilan bir xil qadamlarni bajaradi:
- soxta TARGET papka (ichida `SevimliKassa.exe` o'rniga `app.txt = "v1"`),
- soxta NEW papka (`app.txt = "v2"`),
- `robocopy NEW TARGET` bilan almashtirish,
- sog'liq-bayrog'i (`run-ok`) mantig'i.

**Kutilgan natija — `ok`:** almashtirilgandan keyin `TARGET\app.txt`
`"v2"` bo'ladi va skript `PASS: yangilanish qoldi (v2)` deб yozadi.

**Kutilgan natija — `rollback`:** yangi versiya bayroq yozmaydi (ishga
tushmagan deб hisoblanadi); skript BACKUP dan tiklaydi va `TARGET\app.txt`
qaytadan `"v1"` bo'ladi — `PASS: rollback ishladi (v1)`.

Ikkala holatda ham harness oxirida barcha vaqtinchalik papkalarni o'chiradi.

---

## 2-sinov — to'liq oqim (real ilova, sekinroq)

Bu haqiqiy `robocopy` bilan haqiqiy `SevimliKassa.exe` ni almashtiradi.

### Tayyorgarlik — ikki versiya yig'ish

1. `pos\version.py` da `VERSION = "1.5.0"` — shu versiyani birinchi
   yig'asiz (eski). `KASSA-EXE-YASASH.bat` ni ishga tushiring.
   Chiqqan `dist\SevimliKassa\` papkasini bir chetga saqlang (masalan
   `C:\test\install\` ga ko'chiring — bu "o'rnatilgan" versiya bo'ladi).
2. `pos\version.py` da versiyani `"1.6.0"` ga oshiring. Ko'zga ko'rinishi
   uchun bosh oynaga kichik belgi qo'shsangiz ham bo'ladi (ixtiyoriy).
   Qayta yig'ing. Chiqqan `dist\SevimliKassa\` ni ZIP qiling:
   `SevimliKassa-1.6.0.zip` (ichida `SevimliKassa\SevimliKassa.exe`).

### Variant A — panel orqali (eng haqiqiy)

3. Panelning «Versiyalar» sahifasida `SevimliKassa-1.6.0.zip` ni versiya
   `1.6.0` sifatida yuklang.
4. `C:\test\install\SevimliKassa.exe` ni ishga tushiring (1.5.0).
5. Ilova o'zi serverdan 1.6.0 ni ko'radi, ZIP ni yuklab oladi, SHA-256
   tekshiradi, so'ng «Yangilash» oynasini chiqaradi.
6. «Yangilash» ni bosing. Ilova yopiladi, `apply-update.bat` ishlaydi,
   papka almashtiriladi, yangi versiya ochiladi.

**Tekshirish:**
- Ilova qayta ochilgach versiya `1.6.0` bo'lishi kerak.
- `%APPDATA%\SevimliKassa\update\run-ok` faylida `1.6.0` yozilgan bo'ladi
  (`mark_started()` yozadi).
- `%APPDATA%\SevimliKassa\update\backup` va `new-1.6.0` papkalari
  o'chirilgan bo'ladi (skript oxirida tozalaydi).

### Variant B — rollback'ni real sinash

Buzuq yangilanishda eski versiya tiklanishini ko'rish uchun:

7. 1.6.0 ZIP ichidagi `SevimliKassa.exe` ni ataylab buzing (masalan
   `_internal\python3*.dll` ni o'chiring — shunda yangi exe ishga
   tushmaydi va `run-ok` yozilmaydi). ZIP ni qayta yig'ing.

   > Eslatma: `apply()` ochilgan ZIP ichida `python3*.dll` yo'qligini
   > **oldindan** aniqlaydi va bunday papkani umuman o'rnatmaydi (xavfsiz).
   > Rollback'ni ko'rish uchun DLL bor, lekin exe **ochilgach yiqiladigan**
   > holat kerak — masalan `_internal\base_library.zip` ni buzing. Shunda
   > exe ochiladi-yu, Python yuklanmay yiqiladi, `run-ok` yozilmaydi.

8. Yuqoridagidek yangilang. Yangi exe ochilib yiqiladi, `run-ok` 20 soniya
   ichida paydo bo'lmaydi.

**Tekshirish:**
- `apply-update.bat` BACKUP dan tiklaydi va **eski 1.5.0** qayta ochiladi.
- Do'kon ishlashda davom etadi (buzuq versiyada qolib ketmaydi).

---

## Xavfsizlik eslatmasi

Windows Defender yangi imzosiz `.exe` va `.bat` ni birinchi marta shubhali
deб belgilashi mumkin. Sinovdan oldin `%APPDATA%\SevimliKassa` va o'rnatma
papkasini istisnoga qo'shing (`ANTIVIRUS-RUXSAT.bat` ni ishlating). Bu
updater xatosi emas — imzolanmagan ilovalarning odatiy holati.

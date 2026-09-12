# Shriftlar (Inter)

POS UI birlamchi shrifti — **Inter**. Bu papkaga Inter `.ttf` fayllarini
qo'ysangiz, dastur ochilishida avtomatik yuklanadi (`main.py` bu papkadagi
har qanday `.ttf` ni yuklaydi) va butun interfeys Inter'da ko'rinadi.

Kerakli fayllar (Inter, OFL litsenziyasi — bepul):

```
Inter-Regular.ttf
Inter-Medium.ttf
Inter-SemiBold.ttf
Inter-Bold.ttf
```

## Qanday qo'shiladi (bir marta)

**Variant A — skript bilan (internet bor mashinada):**

```
python pos/fonts/fetch_inter.py
```

Skript 4 ta faylni rasmiy manbadan yuklab, shu papkaga qo'yadi.

**Variant B — qo'lда:**

1. https://github.com/rsms/inter/releases (yoki
   https://fonts.google.com/specimen/Inter) dan Inter'ni yuklab oling.
2. Yuqoridagi 4 ta `.ttf` ni shu papkaga (`pos/fonts/`) ko'chiring.
3. EXE yig'ilганда `KASSA-EXE-YASASH.bat` ularni ichiga oladi.

## Fayl bo'lmasa nima bo'ladi

Dastur avtomatik **Segoe UI** (barcha Windows'da mavjud) ga o'tadi —
Inter'ga juda yaqin, geometrik sans-serif. Ya'ni shrift qo'shilmasa ham
UI professional va toza ko'rinadi; Inter uni yanada yaxshilaydi, lekin
majburiy emas.

> Eslatma: bu loyiha yig'ilgan bulut muhitida Inter yuklab olish manbasi
> (GitHub/CDN) bloklangan edi, shuning uchun `.ttf` fayllar ZIP ichiga
> qo'shilmagan. Yuqoridagi bir qadam bilan o'zingiz qo'shasiz — kod
> allaqachon tayyor, fayllarni qo'ysangiz o'zi ishlatadi.

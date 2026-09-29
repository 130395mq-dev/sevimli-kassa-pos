# 2026-09-29: tekshiruv holati (production relizi emas)

Bu qayd oldingi auditdagi shu mavzularga oid holatlarni yangilaydi.
Birorta production merge yoki umumiy POS relizi bajarilmadi.

## Dalil bilan tekshirilgan

- Windows POS: 256 test o'tdi (12.923 s). Oldingi BAT matnini tekshiradigan
  4 test o'rniga haqiqiy fayl almashtirish/xato holatlarini tekshiradigan
  16 test qo'shildi. Printer uchun 12 regressiya testi shu umumiy songa kiradi.
- `tools/test_windows_update.py`: Windows'da 4 jarayon sinovi o'tdi.
  Kichik maxsus EXE bilan muvaffaqiyat, ishga tushib yiqilish/rollback,
  ochilishi kechikkan tirik jarayon, buzilgan runtime javobi sinaldi.
  Bu to'liq POS oynasi yoki haqiqiy kassadagi o'rnatish sinovini almashtirmaydi.
- Yangi frozen EXE: Qt, Windows printer moduli, 1024x768 offscreen oyna va
  SQLite yozish/qayta ochish/yaxlitlik o'tdi. EXE SHA256:
  `e72f15758f269728aa49a230b5dd1297b97c4823ce7f9438c6f011134f8c16c0`.
- Test monoblok (Windows 10.0.19043 x64): 17:28 dagi izchil SQLite backup
  integrity=ok. 71 ta tarix yozuvi, sent=1:69, boshqa holat:2; sent=0:0.
  Yuborilmagan pul amali va saqlangan savat:0. Bu hisobot qaysi yozuvlar
  haqiqiy savdo ekanini o'zi aniqlamaydi.
- Monoblokda avvalgi frozen runtime tekshiruvi o'tdi (o'rnatmasdan,
  tarmoqsiz alohida bazada). O'rnatilgan eski EXE SHA256:
  `d84e3eeb3b27d1a421234097262e2a98f660e6d45ba01e467509c93ad0073a97`.
- Oddiy ish kompyuterida haqiqiy Q371U printer va skaner sinaldi:
  dona, 21 donali kod, 29 vaznli yorliq, qayta chop etish; USB uzilganida
  navbat ogohlantirishi va UI ishlashi, ulaganda chek chiqishi tasdiqlandi.
  Bevosita tarozidan vazn olish bu sinovga kirmaydi.
- CI uchun eski kodda yaratilgan 3 navbatli chek + 1 pul amali saqlandi.
  Manba koddagi haqiqiy `main()` oflayn katalog/hello keshi bilan UI tayyor
  belgisigacha yetdi; yopilgach navbat payloadlari o'zgarmadi.

## O'rnatish va yangilashdagi tuzatish

Eski updater zaxira ko'chirish natijasini tekshirmasdan davom etardi;
ustidan nusxalash eski/yangi DLL aralashmasini qoldirardi. Installer ham
boshqa kassani nomi bo'yicha majburan o'chirib, papka ustidan yozardi.

Endi yangi nusxa noyob qo'shni papkaga ko'chiriladi, barcha fayllar SHA256
bilan solishtiriladi va uning frozen runtime'i alohida tekshiriladi.
Eski papka zaxira nomiga o'tkazilgach yangi papka joyiga qo'yiladi.
Ko'chirish xatosida oldingi nusxa o'z joyida qoladi. Rollback ham papkani
to'liq almashtiradi; yangi DLL eski nusxaga aralashmaydi.

Ishga tushish belgisi Qt asosiy/kirish oynasi tayyor bo'lgach yoziladi.
Yangi worker versiya, aniq child PID va bir martalik nonce'ni tekshiradi.
Tirik, lekin tayyorligini tasdiqlamagan POS majburan o'chirilmaydi va ikkinchi
nusxa ochilmaydi; zaxira saqlanib, natija `running-unconfirmed-backup-retained`
bo'ladi. Buni muvaffaqiyatli yangilanish deb belgilash mumkin emas.

Yangilanishni tayyorlash UI oqimidan chiqarildi; shu paytda savdo tugmalari
va kiritish vaqtincha o'chiriladi. Xatoda eski dasturda davom etiladi.
ZIP yo'llari va versiya tekshiriladi; mavjud staging papka o'chirilmaydi.
Installer xatosida ko'chma/chala nusxada savdo yashirincha boshlanmaydi.

## Chegaralar va chiqarishdan oldingi ishlar

- 1.18.6 kassasidagi ESKI updater yangi paket ichidagi tuzatish bilan
  orqadan tuzalmaydi. Birinchi o'tish nazorat ostidagi to'liq installer orqali.
- Test monoblokdagi haqiqiy o'rnatish → yangilash → 1.18.6 ga qaytish
  natijasi alohida kutilmoqda; yuborilgan paket baza nusxasi va soxta token
  bilan ishlaydi, yakunda eski dastur joyiga qaytariladi.
- GitHub Actions natijalari alohida tekshiriladi. Lokal testni CI o'tdi deb
  hisoblamaymiz. Release faqat main'dan; bu branch merge qilinmaydi.
- Eski/zaxira/muvaffaqiyatsiz papkalar avtomatik o'chirilmaydi. Disk joyini
  kuzatish va tasdiqlangan tiklash nuqtalari uchun retention rejasi kerak.
- Ikki rename orasida tok uzilsa qo'lda tiklash talab qilinishi mumkin;
  haqiqiy elektr uzilishi/to'la disk/uzoq savdo kuni sinovlari yopilmagan.
- Kassa3 asl cheki, production baza/media backupidan tiklash, tashqi
  ogohlantirish, Railway CI gate, reliz imzosi, vakolatlarning yakuniy
  tekshiruvi va pilot savdo kuni hali ochiq.
- Mahalliy Git credential manager orqali ikkala repo uchun push huquqi
  tasdiqlandi. Avvalgi connector `push=false` cheklovi shu ulanishga tegishli
  edi; u hisob egasining mavjud Git ulanishida to'siq emas.

Sinov jurnallari ishchi paketning `work/sep29-validation/` katalogida:
`update-all-tests.txt`, `native-update-repro/results.json`,
`frozen-update-runtime/result.json`, `ci-offline-ui/`,
`monoblock-preflight-1728/YUBORISH.zip`. Baza/tokenlar Git'ga qo'shilmaydi.

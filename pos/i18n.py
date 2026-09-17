"""
Interfeys tili — O'zbek (asos) va Rus.

Ishlash tamoyili oddiy: manba matn har doim o'zbekcha yoziladi va u
kalit bo'lib xizmat qiladi. `tr()` shu kalitni joriy tilga o'giradi.
Til "uz" bo'lsa — matn o'zgarmaydi (tarjima izlanmaydi ham).

Shu tufayli kod o'qishga qulay qoladi: `tr("Yopish")` — o'zi nima
degani ko'rinib turadi, tarjima faqat kerak bo'lsa qidiriladi.

Interpolatsiyali matnlar `{}` joy egallari bilan yoziladi:

    tr("Katalog yangilandi ({n} ta)").format(n=count)

Til kassa sozlamasida saqlanadi va har bir kassa o'zi tanlaydi.
"""

from __future__ import annotations

#: Joriy til — startda config'dan o'rnatiladi
_lang = "uz"


def set_lang(code: str) -> None:
    global _lang
    _lang = code if code in ("uz", "ru") else "uz"


def get_lang() -> str:
    return _lang


def tr(text: str) -> str:
    if _lang == "ru":
        return _RU.get(text, text)
    return text


#: O'zbekcha manba → ruscha. Kalit — kodda yozilgan aynan o'sha satr.
_RU: dict[str, str] = {
    # --- umumiy tugmalar ---
    "Bekor": "Отмена",
    "Yopish": "Закрыть",
    "Chiqish": "Выход",
    "SAQLASH": "СОХРАНИТЬ",
    "TASDIQLASH": "ПОДТВЕРДИТЬ",
    "OCHISH": "ОТКРЫТЬ",
    "QO'YISH": "ВЫБРАТЬ",
    "TANLASH": "ВЫБРАТЬ",
    "QIDIRISH": "ПОИСК",
    "KIRISH": "ВОЙТИ",
    "ULASH": "ПОДКЛЮЧИТЬ",
    "YAKUNLASH": "ЗАВЕРШИТЬ",
    "TAYYOR": "ГОТОВО",
    "O'chirish": "Удалить",

    # --- menyu ---
    "Chekni keyinga qoldirish": "Отложить чек",
    "Qoldirilgan cheklar": "Отложенные чеки",
    "Tarix": "История",
    "Qaytarish": "Возврат",
    "Oraliq hisobot": "Промежуточный отчёт",
    "Kassaga pul kiritish": "Внести деньги в кассу",
    "Kassadan pul chiqarish": "Изъять деньги из кассы",
    "Ma'lumotlarni yangilash": "Обновить данные",
    "Smenani yopish": "Закрыть смену",
    "Dasturdan chiqish": "Выйти из программы",

    # --- asosiy oyna ---
    "Chek": "Чек",
    "Tovar tanlanmagan": "Товар не выбран",
    "Chapdagi ro'yxatdan tovar tanlang": "Выберите товар из списка слева",
    "Jami:": "Итого:",
    "To'lovga": "К оплате",
    "Mijoz": "Покупатель",
    "Mijozsiz": "Без покупателя",
    "Chek chegirmasi": "Скидка на чек",
    "Chegirma": "Скидка",
    "Shtrix-kod yoki nom": "Штрихкод или название",
    "Onlayn": "Онлайн",
    "Oflayn": "Офлайн",
    # --- aloqa chiroqlari (pastki qator) ---
    "Server": "Сервер",
    "aloqa yo'q": "нет связи",
    "navbatda {n} ta chek": "в очереди чеков: {n}",
    "Oflayn — cheklar kassada saqlanadi": "Офлайн — чеки сохраняются на кассе",
    "Aloqa yaxshi": "Связь в порядке",
    "Noma'lum": "Неизвестно",
    "To'lov turlari yangilandi": "Способы оплаты обновлены",
    "Server bilan aloqa yo'q va smena ochiq emas.": "Нет связи с сервером, и смена не открыта.",
    "Smena ochish uchun server kerak. Internet tiklangach qayta oching.": "Для открытия смены нужен сервер. Откройте снова, когда появится интернет.",
    "Oflayn rejim — aloqa tiklangach cheklar o'zi yuboriladi": "Офлайн-режим — чеки отправятся сами, когда появится связь",
    "Yangilanmoqda…": "Обновление…",
    "Ma'lumotlar yangilanmoqda": "Обновление данных",
    "Narxlar, yangi va o'chirilgan tovarlar": "Цены, новые и удалённые товары",
    "Savdo nuqtasi sozlamalari yuklanmoqda…": "Загружаем настройки точки продаж...",
    "Tovarlar ma'lumotnomasi yuklanmoqda…": "Загружаем справочник товаров...",
    "Kassa bazasi yangilanmoqda…": "Обновляем базу кассы...",
    "Katalog yangilandi": "Каталог обновлён",
    "Yangilab bo'lmadi": "Не удалось обновить",
    "Noma'lum xato": "Неизвестная ошибка",
    "Kassa avvalgi ma'lumotlar bilan ishlashda davom etadi": "Касса продолжит работу с прежними данными",
    "Narx / nom yangilandi": "Обновлены цены / названия",
    "Yangi tovar": "Новые товары",
    "O'chirildi": "Удалено",
    "Hammasi joyida — o'zgarish yo'q": "Всё актуально — изменений нет",
    "Yangi narxlar keyingi chekdan boshlab amal qiladi": "Новые цены действуют со следующего чека",
    "Yangilanmadi: {e}": "Не обновлено: {e}",
    "Katalog yangilandi ({n} ta o'zgarish)": "Каталог обновлён ({n} изменений)",
    "Katalog yangi — o'zgarish yo'q": "Каталог актуален — изменений нет",
    "Miqdor": "Количество",
    "Tovar topilmadi": "Товар не найден",
    "Chek bo'sh": "Чек пуст",
    "Chek qoldirildi": "Чек отложен",
    "Avval chekni yakunlang yoki tozalang": "Сначала завершите или очистите чек",

    # --- kirish ---
    "Kassaga kirish": "Вход в кассу",
    "⌨  Ekran klaviaturasi": "⌨  Экранная клавиатура",
    "⌨  Ekran klaviaturasini yashirish": "⌨  Скрыть экранную клавиатуру",
    "Kassirni tanlang": "Выберите кассира",
    "Kamida 3 raqam kiriting": "Введите минимум 3 цифры",

    # --- ulash (setup) ---
    "Kassani ulash": "Подключение кассы",
    "Server manzili": "Адрес сервера",
    "Kassa logini": "Логин кассы",
    "Kassa paroli": "Пароль кассы",
    "Ulanmoqda…": "Подключение…",
    "Ulandi": "Подключено",
    "Ulanmadi": "Не удалось подключиться",
    "Endi bu so'ralmaydi.": "Больше не спросим.",
    "Login va parolni to'ldiring.": "Введите логин и пароль.",
    "Login va parolni paneldan olasiz: Kassalar bo'limi.":
        "Логин и пароль возьмите в панели: раздел «Кассы».",

    # --- smena ---
    "Smena ochish": "Открытие смены",
    "KASSIR": "КАССИР",
    "RAZMEN PULI (so'm)": "РАЗМЕННЫЕ ДЕНЬГИ (сум)",
    "Smena ochilmadi": "Смена не открыта",
    "Smena yopilmadi": "Смена не закрыта",
    "Kassadagi naqd pulni sanang va kiriting.":
        "Пересчитайте наличные в кассе и введите.",
    "Smena cheki": "Отчёт по смене",

    # --- pul ---
    "Kassaga pul kiritish yoki undan chiqarish.":
        "Внесение или изъятие денег из кассы.",
    "Razmen yoki qo'shimcha pul": "Размен или доп. деньги",
    "Inkassatsiya yoki xarajat": "Инкассация или расход",
    "Saqlanmadi": "Не сохранено",
    "Hisobot": "Отчёт",
    "Katalog": "Каталог",

    # --- to'lov ---
    "To'lov": "Оплата",
    "NAQD QABUL QILISH": "ПРИЁМ НАЛИЧНЫХ",
    "KARTA VA ONLAYN": "КАРТА И ОНЛАЙН",
    "BERILGAN SUMMA": "ПОЛУЧЕНО",
    "QAYTIM": "СДАЧА",
    "Telefon yoki karta raqamini kiriting": "Введите номер телефона или карты",
    # aralash to'lov
    "ARALASH TO'LOV (naqd + karta)": "СМЕШАННАЯ ОПЛАТА (нал + карта)",
    "Aralash to'lov": "Смешанная оплата",
    "QOLGANINI": "ОСТАТОК",
    "QOLDI": "ОСТАЛОСЬ",
    "HAMMASI YOPILDI": "ОПЛАЧЕНО ПОЛНОСТЬЮ",
    "Qatorga bosing, summani tering. «QOLGANINI» — qolgan summani qo'yadi.":
        "Нажмите на строку, наберите сумму. «ОСТАТОК» — поставит остаток.",
    "Karta/onlayn summasi chekdan ko'p": "Сумма карт/онлайн больше чека",
    "Karta/onlayn chekni to'liq yopdi — naqd summasini o'chiring":
        "Карта/онлайн уже закрыли чек — уберите наличные",

    # --- qaytarish ---
    "Qaytariladigan savdoni tanlang": "Выберите продажу для возврата",
    "Qaytariladigan savdo yo'q.": "Нет продаж для возврата.",
    "QAYTARISH YARATISH": "СОЗДАТЬ ВОЗВРАТ",
    "QAYTARISH": "ВОЗВРАТ",
    "Mijozga qanday qaytariladi?": "Как вернуть покупателю?",
    "Pulni qaytarish": "Возврат денег",
    "Qaytarildi": "Возвращено",
    "Qaytarilmadi": "Возврат не выполнен",
    "Hali chek yo'q": "Чеков пока нет",
    "Qoldirilgan chek yo'q": "Нет отложенных чеков",

    # --- tarix (shu smenadagi cheklar, chek raqami bo'yicha qidirish) ---
    "Chek raqami bo'yicha qidirish": "Поиск по номеру чека",
    "Bu raqamli chek topilmadi": "Чек с таким номером не найден",
    "Smena #{n}": "Смена #{n}",
    "Smena (oflayn)": "Смена (оффлайн)",
    "yuborildi": "отправлен",
    "navbatda": "в очереди",
    "Qayta chop etish": "ПОВТОРНАЯ ПЕЧАТЬ",
    "Chek qayta chop etildi": "Чек напечатан повторно",
    "Printer javob bermadi. Chek faylga saqlandi: {p}":
        "Принтер не ответил. Чек сохранён в файл: {p}",
    "Qatorni o'chirish": "Удалить строку",

    # --- mijoz qidirish / yangi mijoz ---
    "Mijozsiz": "Без покупателя",
    "Ism, familiya, telefon yoki karta bo'yicha qidiring":
        "Поиск по имени, фамилии, телефону или карте",
    "Kamida 3 belgi kiriting": "Введите минимум 3 символа",
    "Topilmadi": "Не найдено",
    "Yangi mijoz": "Новый покупатель",
    "Ism": "Имя",
    "Familiya": "Фамилия",
    "Telefon": "Телефон",
    "Karta raqami": "Номер карты",
    "Ism kamida 2 harf bo'lishi kerak": "Имя минимум 2 буквы",
    "Saqlanmoqda…": "Сохранение…",

    # --- ilova yangilanishi ---
    "Dastur haqida": "О приложении",
    "Kassa yangi": "Касса актуальна",
    "Sizda Sevimli Kassa {v} o'rnatilgan": "У вас установлена Sevimli Kassa {v}",
    "Siz allaqachon eng so'nggi versiyadan foydalanyapsiz.": "Вы уже используете самую последнюю версию кассы.",
    "Yangilanishni tekshirish": "Проверить обновление",
    "Tekshirilmoqda…": "Проверка…",
    "Serverdan versiya so'ralmoqda": "Запрашиваем версию у сервера",
    "Tekshirib bo'lmadi": "Не удалось проверить",
    "Server bilan aloqa yo'q. Keyinroq urinib ko'ring.": "Нет связи с сервером. Попробуйте позже.",
    "Yangi versiya bor": "Доступна новая версия",
    "Sevimli Kassa {v}": "Sevimli Kassa {v}",
    "Yuklab olinmoqda… kassa ishlashda davom etadi": "Загрузка… касса продолжает работать",
    "Yangilanish tayyor": "Обновление готово",
    "«Yangilash» bosilgach kassa 10 soniyaga yopilib, yangi versiyada qayta ochiladi.":
        "После «Обновить» касса закроется на 10 секунд и откроется в новой версии.",
    "Yuklab bo'lmadi": "Не удалось загрузить",
    "Keyingi tekshiruvda qayta uriniladi.": "Повторим при следующей проверке.",
    "Yangilash": "Обновить",
    "Yangilanish": "Обновление",
    "Savdo nuqtasi": "Точка продаж",
    "Kassa": "Касса",
    "Server": "Сервер",
    "MAJBURIY YANGILANISH": "ОБЯЗАТЕЛЬНОЕ ОБНОВЛЕНИЕ",
    "YANGILANISH TAYYOR": "ОБНОВЛЕНИЕ ГОТОВО",
    "Sizda {v} o'rnatilgan": "У вас установлена {v}",
    "Nima o'zgardi": "Что изменилось",
    "Keyinroq": "Позже",
    "Hozir yangilash": "Обновить сейчас",
    "Kassa {n} soniyadan so'ng o'zi yangilanadi. Yangilanish 10-20 soniya oladi.":
        "Касса обновится сама через {n} сек. Обновление займёт 10-20 секунд.",
    "Kassa yopilib, yangi versiyada qayta ochiladi (10-20 soniya). Cheklar va navbat saqlanib qoladi.":
        "Касса закроется и откроется в новой версии (10-20 секунд). Чеки и очередь сохранятся.",
    "Yangilanish keyinroq — «Dastur haqida» bo'limidan o'rnatish mumkin":
        "Обновление отложено — установить можно в разделе «О приложении»",
    "Bu muhitda o'zini almashtirish ishlamaydi (exe emas). Fayl: {p}":
        "В этой среде самообновление не работает (не exe). Файл: {p}",

    # --- narx turi ---
    "Narx turi": "Тип цены",
    "Narx turini almashtirish paneldan taqiqlangan": "Смена типа цены запрещена в панели",
    "Narx turi: {n} — chekdagi {c} ta qator qayta narxlandi": "Тип цены: {n} — {c} строк чека пересчитано",
    "Narx turi: {n}": "Тип цены: {n}",

    # --- qayta ulanish ---
    "Qayta ulanish kerak": "Нужно переподключить кассу",
    "Server bu kassani tanimadi (aloqa uzilgan yoki kassa o'chirilgan).":
        "Сервер не узнал эту кассу (связь разорвана или касса удалена).",
    "Paneldagi kassa logini va parolini kiriting.": "Введите логин и пароль кассы из панели.",

    # --- kirish ekrani ---
    "Versiya {v}": "Версия {v}",
    "Dasturni yopish": "Закрыть программу",
    "Login va parolingizni kiriting": "Введите свой логин и пароль",
    "Login": "Логин",
    "Parol": "Пароль",
    "Login va parolni kiriting": "Введите логин и пароль",
    "Login yoki parol noto'g'ri": "Неверный логин или пароль",
    "Oflayn: login yoki parol noto'g'ri. Bu kassada ilgari kirmagan bo'lsangiz — internet kerak.":
        "Офлайн: неверный логин или пароль. Если вы не входили на этой кассе раньше — нужен интернет.",
    "Oflayn — server bilan aloqa yo'q": "Офлайн — нет связи с сервером",
    "Smena #{n} ochiq · {c}": "Смена #{n} открыта · {c}",
    "Smena yopiq — kirgach razmen puli so'raladi": "Смена закрыта — после входа спросим размен",
    "Smena ochish uchun server kerak. Internet tiklangach qayta urinib ko'ring.":
        "Для открытия смены нужен сервер. Попробуйте, когда появится интернет.",
    # davom etish (login eslab qolingan)
    "SMENA OCHISH": "ОТКРЫТЬ СМЕНУ",
    "CHIQISH — boshqa kassir kiradi": "ВЫХОД — войдёт другой кассир",
    "Kirgan: {n}": "Вошёл: {n}",
    "Smena yopiq. Yangi smena ochish uchun tugmani bosing.":
        "Смена закрыта. Нажмите кнопку, чтобы открыть новую смену.",
    "Bu login boshqa kassada ochildi": "Этот логин открыт на другой кассе",

    # --- qoldiq ---
    "«{name}» omborda yo'q": "«{name}» нет на складе",
    "«{name}»: omborda {n} ta": "«{name}»: на складе {n}",

    # --- til ---
    "Til": "Язык",
    "O'zbekcha": "Узбекский",
    "Ruscha": "Русский",
    "Til o'zgardi. Dasturni qayta oching.":
        "Язык изменён. Перезапустите программу.",
}

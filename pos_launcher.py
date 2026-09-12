"""
EXE kirish nuqtasi.

PyInstaller `pos/main.py` ni to'g'ridan-to'g'ri ishga tushirsa, u
`__main__` bo'lib qoladi va `from . import ...` (paket importi) ishlamaydi.
Shuning uchun EXE shu faylni ishga tushiradi — u esa `pos` ni paket
sifatida import qiladi, natijada ichki nisbiy importlar to'g'ri ishlaydi.

Chiqish: `main()` qaytgach jarayon MAJBURAN tugatiladi (os._exit). Kassa
kiosk-dastur — biror yordamchi oqim yoki Qt obyekti tufayli jarayon
«osilib» qolmasligi kerak: kassir «Chiqish» ni bosdi — dastur yopildi.
"""

import os
import sys

from pos.main import main

if __name__ == "__main__":
    code = 1
    try:
        code = int(main() or 0)
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)

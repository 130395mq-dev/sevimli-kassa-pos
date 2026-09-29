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

if __name__ == "__main__":
    code = 1
    try:
        if "--check-runtime" in sys.argv:
            # Before importing main/config or running installer/autostart.
            if len(sys.argv) != 3 or sys.argv[1] != "--check-runtime":
                raise ValueError("Usage: --check-runtime NEW_RESULT_DIRECTORY")
            from pos.runtime_check import run
            code = run(sys.argv[2])
        elif "--apply-update" in sys.argv:
            if len(sys.argv) != 3 or sys.argv[1] != "--apply-update":
                raise ValueError("Usage: --apply-update PLAN_FILE")
            from pos.update_worker import run
            code = run(sys.argv[2])
        else:
            from pos.main import main
            code = int(main() or 0)
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(code)

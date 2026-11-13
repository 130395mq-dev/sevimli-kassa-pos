"""Sinov haydovchisi: HAQIQIY `pos.main.main()` ni ekransiz yurgizadi.

Faqat testlar uchun (pos/test_dastur_ochilishi.py) — alohida jarayonda:

    python -m pos.sinov_haydovchi reja.json

`main()` — bitta katta funksiya; 12.11.2026 xatosi aynan uning ichida edi
(dastur ochilganda qaysi smenaga kirish). Uni bo'laklab sinab bo'lmaydi,
shuning uchun butun dastur haqiqiy oynalari bilan ochiladi, faqat:

  * modal oynalar (razmen, «Yopilsinmi?», chek ko'rinishi, xabarlar)
    o'zi javob beradi;
  * chop etish matnni qog'ozga emas, natijaga yozadi;
  * server — testdagi mahalliy soxta server (config.json dagi manzil).

Reja: {"actions": [...], "razmen": 100000, "out": "natija.json"}.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out: dict = {"steps": [], "boxes": [], "printed": [], "errors": []}

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    import pos.main as M
    from pos import config as cfg, printer, updater
    from pos.cart import PaymentPlan
    from pos.store import Store
    from pos.ui import dialogs
    from pos.ui.login_screen import LoginScreen
    from pos.ui.main_window import MainWindow

    # ---- modal oynalar o'zi javob beradi
    def cash_exec(self):
        self.set_amount(int(plan.get("razmen", 100_000)))
        return type(self).Accepted

    dialogs.OpeningCashDialog.exec = cash_exec
    dialogs.CloseShiftDialog.exec = lambda self: type(self).Accepted
    dialogs.ReceiptDialog.exec = lambda self: 0

    def box(kind):
        def show(*args, **kwargs):
            out["boxes"].append([kind, str(args[1]) if len(args) > 1 else "",
                                 str(args[2]) if len(args) > 2 else ""])
            return QMessageBox.Ok
        return staticmethod(show)

    for kind in ("warning", "critical", "information"):
        setattr(QMessageBox, kind, box(kind))

    def fake_print(text, printer_name="", name="chek"):
        out["printed"].append([name, text])
        return True, Path("chop-etilmadi.txt")

    printer.print_text = fake_print

    def control(**body):
        req = urllib.request.Request(
            cfg.load().base + "/__control", data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()

    def finish(code: int) -> None:
        try:
            store = Store(cfg.config_dir() / "kassa.db")
            out["journal"] = [dict(r) for r in store.db.execute("SELECT * FROM shifts ORDER BY seq")]
            out["unsent"] = store.unsent_count()
            out["unsent_cash"] = store.unsent_cash_count()
            out["rejected"] = store.rejected_count()
            store.close()
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"natija o'qilmadi: {e!r}")
        Path(plan["out"]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        if code:
            os._exit(code)
        QApplication.quit()

    def scenario():
        window = next(w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow))
        login = window.findChild(LoginScreen)
        store = window.backend.store

        def state(label):
            out["steps"].append({
                "at": label,
                "login_visible": login.isVisible(),
                "resume_mode": bool(login.resume_mode),
                "enabled": window.centralWidget().isEnabled(),
                "shift_label": window.shift_label.text(),
                "alert": "" if window.alert_bar.isHidden() else window.alert_bar.text(),
                "current": (store.journal_current() or {}).get("uuid"),
            })

        for action in plan["actions"]:
            name, _, arg = action.partition(":")
            if name == "state":
                state(arg or action)
            elif name == "login":
                login.login.emit("kassir", "parol")
            elif name == "resume":
                login.resume_requested.emit()
            elif name == "sell":
                for _ in range(int(arg or 1)):
                    window.cart.add(store.by_barcode("478"))
                    window.refresh()
                    pay = PaymentPlan(total=window.cart.total)
                    pay.add_cash(window.cart.total)
                    with mock.patch("pos.ui.main_window.PaymentDialog") as dialog:
                        dialog.Accepted = 1
                        dialog.return_value.plan = pay
                        dialog.return_value.exec.return_value = 1
                        window.open_payment()
                    if not window.cart.is_empty:
                        out["errors"].append("to'lovdan keyin savat bo'shamadi")
                    yield 150
            elif name == "report":
                window.backend.menu_action("report")
            elif name == "close":
                window.backend.menu_action("close_shift")
            elif name == "cash":
                window.backend.cash("out", int(arg or 10_000) * 100, "sinov")
            elif name in ("offline", "online"):
                control(online=(name == "online"))
            elif name == "reject":
                control(reject_next=int(arg or 1))
            elif name == "wait_synced":
                waited = 0
                check = Store(cfg.config_dir() / "kassa.db")
                try:
                    while waited < 20_000 and (
                            check.unsent_count() or check.unsent_cash_count()
                            or check.journal_pending()):
                        yield 200
                        waited += 200
                    if waited >= 20_000:
                        out["errors"].append("wait_synced: 20 soniyada yetmadi")
                finally:
                    check.close()
            elif name == "wait":
                yield int(arg or 500)
            else:
                out["errors"].append(f"noma'lum amal: {action}")
            yield 80
        finish(0)

    steps = {}

    def advance():
        try:
            delay = next(steps["gen"])
        except StopIteration:
            return
        except Exception as e:  # noqa: BLE001 — sinov xatosi natijaga yoziladi
            import traceback

            out["errors"].append(traceback.format_exc()[-1500:] or repr(e))
            finish(4)
            return
        QTimer.singleShot(int(delay), advance)

    def on_error(kind, value, tb):
        # Qt tugma/signal ichidagi xatoni yutib yuboradi (faqat chop etadi) —
        # sinovda u XATO: kassirning qo'lida dastur shunday «jim» buzilardi.
        import traceback

        out["errors"].append("".join(traceback.format_exception(kind, value, tb))[-1500:])

    def start():
        sys.excepthook = on_error
        steps["gen"] = scenario()
        QTimer.singleShot(int(plan.get("limit_ms", 90_000)),
                          lambda: (out["errors"].append("vaqt tugadi"), finish(3)))
        advance()

    # main() oxirida `QTimer.singleShot(0, _upd.mark_started)` bor — ssenariy
    # shu yerdan, ishlab turgan Qt sikli ichidan boshlanadi.
    updater.mark_started = lambda: QTimer.singleShot(300, start)
    return int(M.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())

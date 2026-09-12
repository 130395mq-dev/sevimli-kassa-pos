"""Render real Qt screens in CI without any server or store connection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from decimal import Decimal
from PySide6.QtWidgets import QApplication
from pos.cart import Product
from pos.ui.main_window import MainWindow
from pos.ui.login_screen import LoginScreen
from pos.ui.payment_dialog import PaymentDialog
from pos.ui import theme

class PreviewBackend:
    methods = [{"code":"naqd","name":"Naqd","is_cash":True},
               {"code":"card","name":"Karta","is_cash":False}]
    products = [Product(i+1, str(i+1), name, price * 100, stock=20)
        for i,(name,price) in enumerate([
            ("Sevimli yangi non", 4000), ("Sut 1 litr", 12500),
            ("Coca-Cola 1.5 litr", 16000), ("Tuxum 10 dona", 18000),
            ("Guruch Lazer 1 kg", 22000), ("Sariyog' 200 g", 24000),
            ("Olma", 14000), ("Choy 100 g", 9500),
            ("Shokolad", 19000), ("Qatiq 500 ml", 8000),
            ("Ichimlik suvi 1.5 l", 3500), ("Pechenye 300 g", 15000)])]
    def search(self, text): return self.products
    def is_favorite(self, pid): return pid in (1,2,5)
    def toggle_favorite(self, pid): return False

def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(f"QWidget {{ font-family: 'Segoe UI'; color: {theme.INK}; }}")
    out = Path("previews")
    out.mkdir(exist_ok=True)
    backend = PreviewBackend()
    win = MainWindow(backend, animated_bg=False)
    win.shift_label.setText("Smena #14")
    for width,height in [(1366,768), (1280,720), (1920,1080)]:
        win.resize(width,height)
        win.show()
        app.processEvents()
        assert win.width() == width, ("layout too wide", win.width(), width)
        win.grab().save(str(out / f"kassa-empty-{width}.png"))
    win.resize(1366,768)
    for p in backend.products[:4]:
        win.cart.add(p, Decimal(2))
    win.refresh()
    app.processEvents()
    win.grab().save(str(out / "kassa-cart.png"))
    dialog = PaymentDialog(win.cart.total, backend.methods, win)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "payment.png"))
    dialog.close()
    login = LoginScreen(win, "SEVIMLI", "Kassa 1")
    login.setGeometry(win.rect())
    login.show()
    app.processEvents()
    login.grab().save(str(out / "login.png"))
    print("UI screenshots rendered successfully")

if __name__ == "__main__":
    main()

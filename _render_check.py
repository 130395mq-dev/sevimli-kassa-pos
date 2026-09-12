import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import sys
from decimal import Decimal
sys.path.insert(0, os.path.dirname(__file__))
from PySide6.QtWidgets import QApplication
app=QApplication(sys.argv)
class P:
    def __init__(s,i,n,pr,st,w=False): s.id=i;s.name=n;s.price=pr;s.stock=st;s.is_weight=w
NAMES=[("697-4 SHIKILDOK",48000,1),("AAA BONA skazochniy ray 2kg shirinlik",52000,0),
 ("BONYA ANGEL XAMIR SOMSA uchun 2kg",28000,0),("BRAVO shirinlik ASSORTI 2 kg sht",78000,0),
 ("BURCU kalampir bonka 320 gr",32000,1),("Bambina Cotton BREAST PAD 40sht",50000,0),
 ("ALGO 15 ml BPA FREE",18000,0),("ALGO 330 ml butilka №9121",21000,15),
 ("ALGO ART №9140 butilka",24000,0),("ALPRO COCONUT 1 l 0,9%",47000,2),
 ("ALPRO NUTTY ALMOND 1 L",47000,1),("ART BAKERY ROSHEN COCOA cookies",15000,36),
 ("ASAL LANGNESE ACACIA HONEY 500gr",199000,0)]
class B:
    def __init__(s):
        s._p=[P(i+1,*a) for i,a in enumerate(NAMES)]
        s._f={1,3,5,8}  # sevimlilar (yulduzchali)
        s.methods=[]
    def search(s,t="",l=200):
        if t: return [p for p in s._p if t.lower() in p.name.lower()]
        return [p for p in s._p if p.id in s._f]   # BO'SH -> faqat sevimlilar
    def is_favorite(s,p): return p in s._f
    def toggle_favorite(s,p): return False
    def find_by_barcode(s,c): return None
    def ask_quantity(s,l): return None
    def ask_customer(s): return None
    def ask_discount(s,c): return None
    def submit(s,c,p): pass
    def menu_action(s,a): pass

from pos.ui.main_window import MainWindow
b=B(); win=MainWindow(b, animated_bg=False)
win.shift_label.setText("Smena #14 · Akmal"); win.status_label.setText("● Onlayn · navbat 0")

# 1) BO'SH holat -> faqat sevimlilar
win.fill_catalog(b.search("")); win.refresh()
win.resize(1366,768); win.show(); app.processEvents(); app.processEvents()
win.grab().save("/home/claude/grid_fav.png"); print("saved grid_fav (favlar:", len(b.search("")),")")

# 2) QIDIRUV -> topilganlar
win.fill_catalog(b.search("a")); win.refresh(); app.processEvents(); app.processEvents()
win.grab().save("/home/claude/grid_search.png"); print("saved grid_search (topildi:", len(b.search("a")),")")
print("OK")

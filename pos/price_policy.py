"""Apply panel prices between receipts; never mutate an open/paid receipt."""
from copy import deepcopy


class PricePolicy:
    def __init__(self, backend, cart, *, busy=lambda: False, applied=lambda changed: None,
                 deferred=lambda: None):
        self.backend = backend
        self.cart = cart
        self.busy = busy
        self.applied = applied
        self.deferred = deferred
        self.pending = None

    def offer(self, info):
        self.pending = deepcopy({key: info.get(key) for key in
            ("price_types", "default_price_type", "price_policy_revision")})
        if (self.pending["price_types"] or []) == self.backend.price_types and (
            self.pending["default_price_type"] or ""
        ) == self.backend.default_price_type and (
            self.pending["price_policy_revision"] or ""
        ) == (self.backend.store.get("price_policy_ack") or ""):
            self.pending = None
            return
        if not self.apply_if_idle():
            self.deferred()

    def apply_if_idle(self):
        if self.pending is None or not self.cart.is_empty or self.busy():
            return False
        policy = self.pending
        previous = self.backend.price_type_id
        self.backend.setup_price_types(policy["price_types"] or [], policy["default_price_type"] or "")
        # Ack is sent by the background worker only when every old receipt is sent.
        self.backend.store.set("price_policy_ack", policy["price_policy_revision"] or "")
        self.pending = None
        self.applied(previous != self.backend.price_type_id)
        return True


def bind_price_policy(backend, window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .i18n import tr

    def applied(changed):
        window.set_price_type(backend.price_type_name, backend.price_type_is_default, False)
        window.fill_catalog(backend.search(window.scan_input.text().strip()))
        if changed:
            window.flash(tr("Narx turi: {n}").format(n=backend.price_type_name))

    policy = PricePolicy(
        backend, window.cart, busy=lambda: QApplication.activeModalWidget() is not None,
        applied=applied,
        deferred=lambda: window.flash(tr("Yangi narx turi keyingi chekdan qo'llanadi")),
    )
    window.cart_changed.connect(policy.apply_if_idle)
    policy.timer = QTimer(window)
    policy.timer.setInterval(250)
    policy.timer.timeout.connect(policy.apply_if_idle)
    policy.timer.start()
    return policy

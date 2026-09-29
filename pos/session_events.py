"""Deliver background session replies only to the session that requested them."""
from PySide6.QtCore import QObject, Signal, Slot


class SessionEvents(QObject):
    # value, session token used by the request (never logged)
    renewed = Signal(str, str)
    lost = Signal(str, str)

    def __init__(self, hub, on_renewed, on_lost):
        super().__init__()
        self.hub = hub
        self.on_renewed = on_renewed
        self.on_lost = on_lost
        self.renewed.connect(self._renewed)
        self.lost.connect(self._lost)

    @Slot(str, str)
    def _renewed(self, token, requested_session):
        if requested_session and self.hub.session == requested_session:
            self.on_renewed(token)

    @Slot(str, str)
    def _lost(self, message, requested_session):
        if requested_session and self.hub.session == requested_session:
            self.on_lost(message)

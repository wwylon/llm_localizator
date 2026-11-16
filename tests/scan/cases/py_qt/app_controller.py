import logging
from PySide6.QtCore import QObject, QSettings, Signal, Property

log = logging.getLogger(__name__)


class AppController(QObject):
    statusChanged = Signal()
    toastRequested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("pywarp", "app")
        self._status = "Disconnected"
        self._reason = "Connect to create a private route through Cloudflare."
        self._reason_code = ""
        self._mode = "warp"

    def on_error(self):
        log.warning("Connection failed with code %s", 3)
        self._set_reason("Ready when you are", "Connect to create a private route.")
        self.toastRequested.emit("Could not reach the service", "error")
        self._run(["warp-cli", "connect"])

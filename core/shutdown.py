"""
core/shutdown.py
Manejador de señales SIGINT y SIGTERM para apagado seguro y guardado atómico.
"""

import sys
import signal

class GracefulShutdownHandler:
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        sig_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM"
        sys.stderr.write(f"\n[!] Señal {sig_name} recibida. Iniciando apagado seguro...\n")
        self.shutdown_requested = True

    def should_stop(self) -> bool:
        return self.shutdown_requested

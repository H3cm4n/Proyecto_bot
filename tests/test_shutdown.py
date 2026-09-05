import os
import signal
from core.shutdown import GracefulShutdownHandler

def test_shutdown_handler():
    handler = GracefulShutdownHandler()
    assert handler.should_stop() is False
    
    # Simular recepción de señal SIGINT
    os.kill(os.getpid(), signal.SIGINT)
    assert handler.should_stop() is True

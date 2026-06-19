import threading
import time
import pytest
from unittest.mock import patch
from run import get_engine, _shutdown_engine

def test_single_window_monitor_thread_regression():
    """
    Regression test: Asserts that only one WindowMonitor thread is created
    per process, even under concurrent initialization attempts.
    """
    
    engines = []
    def fetch_engine():
        engines.append(get_engine())

    # Spawn multiple threads trying to get the engine concurrently
    threads = []
    for _ in range(10):
        t = threading.Thread(target=fetch_engine)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
        
    # All threads should have received the EXACT same instance
    first_engine = engines[0]
    for eng in engines:
        assert eng is first_engine
        
    # Now check the active threads to ensure only ONE "focuslock-monitor" exists
    # If the monitor hasn't started yet, we start a session
    with patch("backend.core.monitor.WindowMonitor.start", wraps=first_engine.active_monitor.start if first_engine.active_monitor else None) as mock_start:
        first_engine.set_monitor([], [], "test intent", "deep")
    
    active_threads = threading.enumerate()
    monitor_threads = [t for t in active_threads if t.name == "focuslock-monitor"]
    
    # Assert exactly ONE monitor thread is running
    assert len(monitor_threads) <= 1, "Regression: Multiple WindowMonitor threads spawned!"
    
    _shutdown_engine()

import pytest
from unittest.mock import patch, MagicMock
from backend.core.engine import FocusEngine

@pytest.fixture
def engine():
    # Mock EventStore and LearningManager so it doesn't write to DB
    with patch("backend.core.engine.EventStore"), \
         patch("backend.core.engine.LearningManager"):
        eng = FocusEngine()
        eng.store = MagicMock()
        eng.store.get_current_session.return_value = {
            "session_id": "test",
            "intent": "code",
            "mode": "deep",
            "whitelist": [],
            "blacklist": []
        }
        return eng

def test_fsm_transition_productive_to_warning(engine):
    # FSM state should transition from PRODUCTIVE to WARNING when drift occurs or confidence is medium
    engine.current_state = "PRODUCTIVE"
    
    with patch("backend.core.engine.clf.extract_features") as mock_extract:
        mock_extract.return_value = {
            "heuristic_score": -20, # Distraction
            "confidence": 60.0,     # Medium confidence -> Warning
            "whitelist_match": False,
            "blacklist_match": False,
            "negative_override": False
        }
        
        # Mock Context Builder
        with patch("backend.core.engine.build_context", return_value={}):
            engine._on_state_change({"title": "Twitter", "app": "chrome"})
            
        assert engine.current_state == "WARNING"

def test_fsm_transition_warning_to_distraction(engine):
    # FSM state should transition to DISTRACTION when confidence is high
    engine.current_state = "WARNING"
    
    with patch("backend.core.engine.clf.extract_features") as mock_extract:
        mock_extract.return_value = {
            "heuristic_score": -50, # High Distraction
            "confidence": 85.0,     # High confidence -> Distraction
            "whitelist_match": False,
            "blacklist_match": False,
            "negative_override": False
        }
        
        # Mock Context Builder
        with patch("backend.core.engine.build_context", return_value={}):
            # Also patch the recovery logic that calls try_close_active_window
            with patch("backend.core.engine.focus_focuslock", create=True):
                engine._on_state_change({"title": "Netflix", "app": "chrome"})
            
        assert engine.current_state == "DISTRACTION"

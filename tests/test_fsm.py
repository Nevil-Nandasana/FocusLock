"""
FSM tests for FocusEngine
=========================
Bugs fixed in this revision:
  1. Fixture used `return eng` outside the `with patch(...)` blocks — patches
     were unbound before any test ran.  Fixed by using `yield eng` inside the
     patch context so mocks stay active for the entire test lifetime.

  2. `WindowMonitor` was not patched, so `__init__` spawned a real background
     thread that tried to import `window_utils` (which crashes pre-fix).

  3. `focus_focuslock` was patched at the wrong path
     (`backend.core.engine.focus_focuslock`) while the engine does a *local*
     import (`from backend.core.window_utils import focus_focuslock`).
     The correct patch target is `backend.core.window_utils.focus_focuslock`.

  4. Added `test_fsm_illegal_transition_clamped` to verify that
     ALLOWED_TRANSITIONS actually prevents PRODUCTIVE → DISTRACTION jumps.
"""
import pytest
from unittest.mock import patch, MagicMock
from backend.core.engine import FocusEngine, ALLOWED_TRANSITIONS


@pytest.fixture
def engine():
    """
    Return a FocusEngine with all I/O mocked.

    The `with` blocks must stay open for the entire test — hence `yield`.

    Patch strategy:
    - ``EventStore``: replaced with a class-level mock so ``__init__`` gets
      a mock store instance.  The mock store's ``get_current_session()`` returns
      ``None`` so ``_check_resume_session`` exits immediately without touching
      ``intent_engine``.
    - ``LearningManager`` / ``WindowMonitor``: prevent thread spawning.
    - ``intent_engine``: prevents ``_parse_intent`` from calling real NLP code
      during ``__init__`` if a session is accidentally resumed.
    - After construction we replace ``eng.store`` with a fully configured mock
      that returns a real session dict.
    """
    with patch("backend.core.engine.EventStore") as MockStoreClass, \
         patch("backend.core.engine.LearningManager"), \
         patch("backend.core.engine.WindowMonitor"), \
         patch("backend.core.engine.intent_engine"):

        # _check_resume_session must return early — return None so no session is resumed
        MockStoreClass.return_value.get_current_session.return_value = None

        eng = FocusEngine()

        # Now swap in a fully configured store mock for the tests themselves
        store_instance = MagicMock()
        store_instance.get_current_session.return_value = {
            "session_id": "test-session",
            "intent":    "code",
            "mode":      "deep",
            "whitelist": [],
            "blacklist": [],
        }
        # register_violation() calls get_violation_count() and compares against int
        store_instance.get_violation_count.return_value = 0
        store_instance.get_penalty_seconds.return_value = 0
        eng.store = store_instance


        yield eng


# ── Allowed-transition tests ──────────────────────────────────────────────────

def test_fsm_transition_productive_to_warning(engine):
    """PRODUCTIVE → WARNING is an allowed transition."""
    engine.current_state = "PRODUCTIVE"

    with patch("backend.core.engine.clf.extract_features") as mock_extract, \
         patch("backend.core.engine.build_context", return_value={}):

        mock_extract.return_value = {
            "heuristic_score":    -20,   # negative → distraction signal
            "confidence":          60.0, # medium → WARNING (not DISTRACTION)
            "whitelist_match":    False,
            "blacklist_match":    False,
            "negative_override":  False,
            "semantic_similarity": 0.0,
            "ml_prob":             0.0,
        }

        engine._on_state_change({"title": "Twitter", "app": "chrome"})

    assert engine.current_state == "WARNING"


def test_fsm_transition_warning_to_distraction(engine):
    """WARNING → DISTRACTION is an allowed transition."""
    engine.current_state = "WARNING"

    with patch("backend.core.engine.clf.extract_features") as mock_extract, \
         patch("backend.core.engine.build_context", return_value={}), \
         patch("backend.core.window_utils.focus_focuslock", return_value=False):

        mock_extract.return_value = {
            "heuristic_score":    -50,   # strong distraction
            "confidence":          85.0, # high → DISTRACTION
            "whitelist_match":    False,
            "blacklist_match":    False,
            "negative_override":  False,
            "semantic_similarity": 0.0,
            "ml_prob":             0.0,
        }

        engine._on_state_change({"title": "Netflix", "app": "chrome"})

    assert engine.current_state == "DISTRACTION"


# ── ALLOWED_TRANSITIONS enforcement ──────────────────────────────────────────

def test_fsm_illegal_transition_clamped(engine):
    """
    PRODUCTIVE → DISTRACTION is NOT in ALLOWED_TRANSITIONS.

    The FSM must clamp the jump to WARNING rather than allowing a direct skip.
    This test will catch any future regression that removes the guard.
    """
    assert "DISTRACTION" not in ALLOWED_TRANSITIONS["PRODUCTIVE"], (
        "Pre-condition: PRODUCTIVE → DISTRACTION must not be in ALLOWED_TRANSITIONS"
    )

    engine.current_state = "PRODUCTIVE"

    # Feed a strong distraction signal with high confidence to produce a raw
    # final_state of DISTRACTION before the FSM guard runs.
    with patch("backend.core.engine.clf.extract_features") as mock_extract, \
         patch("backend.core.engine.build_context", return_value={}), \
         patch("backend.core.window_utils.focus_focuslock", return_value=False):

        mock_extract.return_value = {
            "heuristic_score":    -100,  # very strong distraction
            "confidence":          90.0, # high confidence
            "whitelist_match":    False,
            "blacklist_match":    False,
            "negative_override":  False,
            "semantic_similarity": 0.0,
            "ml_prob":             0.0,
        }

        engine._on_state_change({"title": "YouTube", "app": "chrome"})

    # Must be clamped to WARNING, not DISTRACTION
    assert engine.current_state == "WARNING", (
        f"Expected WARNING (FSM guard), got {engine.current_state!r}"
    )


# ── Sanity-check the ALLOWED_TRANSITIONS table itself ─────────────────────────

def test_allowed_transitions_table_complete():
    """Every state must have an entry in ALLOWED_TRANSITIONS."""
    required_states = {"PRODUCTIVE", "WARNING", "DISTRACTION"}
    assert required_states == set(ALLOWED_TRANSITIONS.keys())


def test_distraction_cannot_reach_productive_directly():
    """DISTRACTION → PRODUCTIVE is not allowed (must go through WARNING)."""
    assert "PRODUCTIVE" not in ALLOWED_TRANSITIONS["DISTRACTION"]

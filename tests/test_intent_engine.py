import pytest
from backend.ml.intent_engine import IntentEngine

@pytest.fixture
def intent_engine():
    return IntentEngine()

def test_parse_empty_intent(intent_engine):
    profile = intent_engine.parse("")
    assert profile.intent_key == "global"
    assert profile.strength == 0.0
    # Even without intent, basic negative signals should exist
    assert len(profile.negative_signals) > 0

def test_parse_coding_intent(intent_engine):
    profile = intent_engine.parse("debug my python backend")
    assert profile.intent_key == "coding"
    assert profile.goal_verb == "debug"
    assert profile.goal_subject == "python"
    assert profile.strength > 0.5
    assert "youtube" in profile.negative_signals
    assert "vscode" in profile.positive_signals or "pycharm" in profile.positive_signals or "github" in profile.positive_signals

def test_parse_vague_intent(intent_engine):
    profile = intent_engine.parse("do stuff")
    assert profile.intent_key == "global"
    assert profile.strength < 0.5

def test_scoring_negative_override(intent_engine):
    profile = intent_engine.parse("debug python")
    # Score a very distracted activity
    res = profile.score_activity("watching netflix and scrolling tiktok", app_name="netflix")
    assert res["negative_override"] is True
    assert res["intent_boost"] < 0

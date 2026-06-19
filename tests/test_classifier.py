import pytest
from backend.ml.classifier import FeatureClassifier

@pytest.fixture
def classifier():
    return FeatureClassifier()

def test_extract_features_empty_context(classifier):
    # Edge case: completely empty context
    features = classifier.extract_features(
        context={},
        intent="",
        mode="deep",
        whitelist=[],
        blacklist=[]
    )
    assert isinstance(features, dict)
    assert "heuristic_score" in features
    assert features["heuristic_score"] == 0

def test_extract_features_whitelist_override(classifier):
    # Edge case: whitelist should force whitelist_match to True
    features = classifier.extract_features(
        context={"normalized_text": "using figma for design"},
        intent="design something",
        mode="deep",
        whitelist=["figma"],
        blacklist=[]
    )
    assert features["whitelist_match"] is True
    assert features["confidence"] == 100.0

def test_extract_features_blacklist_override(classifier):
    # Edge case: blacklist should force blacklist_match to True
    features = classifier.extract_features(
        context={"normalized_text": "watching youtube"},
        intent="code",
        mode="deep",
        whitelist=[],
        blacklist=["youtube"]
    )
    assert features["blacklist_match"] is True
    assert features["confidence"] == 100.0

def test_extract_features_huge_text(classifier):
    # Edge case: extremely large text to ensure it doesn't crash
    huge_text = "youtube " * 10000
    features = classifier.extract_features(
        context={"normalized_text": huge_text},
        intent="",
        mode="deep",
        whitelist=[],
        blacklist=["youtube"]
    )
    assert features["blacklist_match"] is True

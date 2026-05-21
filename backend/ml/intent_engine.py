"""
IntentEngine — Deep Intent Awareness Layer
==========================================
Parses a natural-language intent string (e.g. "debug my Python API") into a
structured IntentProfile that drives scoring inside the classifier.

Replaces the old flat "+20 for any keyword match" with:
  • positive_signals  → apps/keywords that confirm the user is ON TASK
  • negative_signals  → apps/keywords that are DISTRACTIONS for this specific goal
  • strength (0-1)    → how specific the intent is (scales signal intensity)
  • intent_key        → canonical bucket ("coding", "design", "writing", "learning", …)

No external NLP packages required — pure stdlib string heuristics + domain vocab.
"""

import re
from dataclasses import dataclass, field
from typing import List

# ── Domain Vocabulary ─────────────────────────────────────────────────────────
DOMAIN_VOCAB = {
    "coding": {
        "verbs": [
            "code",
            "build",
            "debug",
            "develop",
            "program",
            "implement",
            "fix",
            "refactor",
            "deploy",
            "script",
            "automate",
            "test",
            "review",
            "ship",
            "compile",
            "integrate",
        ],
        "subjects": [
            "python",
            "javascript",
            "typescript",
            "c++",
            "java",
            "rust",
            "go",
            "api",
            "backend",
            "frontend",
            "function",
            "bug",
            "feature",
            "app",
            "service",
            "database",
            "algorithm",
            "script",
            "bot",
            "cli",
            "sdk",
            "endpoint",
            "migration",
            "schema",
        ],
        "positive_signals": [
            "pycharm",
            "vs code",
            "vscode",
            "github",
            "stackoverflow",
            "terminal",
            "docker",
            "intellij",
            "eclipse",
            "jupyter",
            "postman",
            "insomnia",
            "git",
            "bash",
            "powershell",
            "cmd",
            "python",
            "node",
            "npm",
        ],
        "negative_signals": [
            "youtube",
            "netflix",
            "twitter",
            "instagram",
            "tiktok",
            "reddit",
            "facebook",
            "steam",
            "game",
            "twitch",
            "shopping",
            "amazon",
            "snapchat",
            "pinterest",
        ],
    },
    "design": {
        "verbs": [
            "design",
            "create",
            "sketch",
            "prototype",
            "draw",
            "wireframe",
            "style",
            "brand",
            "layout",
            "animate",
            "illustrate",
            "mockup",
        ],
        "subjects": [
            "ui",
            "ux",
            "logo",
            "figma",
            "mockup",
            "icon",
            "graphic",
            "visual",
            "color",
            "font",
            "animation",
            "illustration",
            "banner",
            "thumbnail",
            "landing page",
            "flow",
            "component",
            "typography",
        ],
        "positive_signals": [
            "figma",
            "photoshop",
            "illustrator",
            "canva",
            "sketch",
            "dribbble",
            "behance",
            "xd",
            "affinity",
            "zeplin",
            "framer",
            "spline",
        ],
        "negative_signals": [
            "youtube",
            "netflix",
            "twitter",
            "tiktok",
            "reddit",
            "facebook",
            "steam",
            "game",
            "twitch",
            "shopping",
        ],
    },
    "writing": {
        "verbs": [
            "write",
            "draft",
            "edit",
            "author",
            "compose",
            "document",
            "blog",
            "journal",
            "summarize",
            "proofread",
            "outline",
            "narrate",
        ],
        "subjects": [
            "essay",
            "report",
            "article",
            "blog",
            "docs",
            "notes",
            "paper",
            "content",
            "story",
            "script",
            "email",
            "proposal",
            "research",
            "chapter",
            "brief",
            "copy",
            "thesis",
        ],
        "positive_signals": [
            "docs",
            "notion",
            "word",
            "grammarly",
            "obsidian",
            "typora",
            "medium",
            "google docs",
            "hemingway",
            "scrivener",
            "ulysses",
            "bear",
        ],
        "negative_signals": [
            "youtube",
            "netflix",
            "twitter",
            "instagram",
            "tiktok",
            "reddit",
            "facebook",
            "steam",
            "game",
            "twitch",
        ],
    },
    "learning": {
        "verbs": [
            "learn",
            "study",
            "read",
            "watch",
            "understand",
            "practice",
            "explore",
            "research",
            "review",
            "follow",
            "complete",
            "finish",
        ],
        "subjects": [
            "course",
            "tutorial",
            "documentation",
            "book",
            "topic",
            "concept",
            "lesson",
            "lecture",
            "chapter",
            "skill",
            "exam",
            "test",
            "quiz",
            "module",
            "certification",
        ],
        "positive_signals": [
            # YouTube is PRODUCTIVE when the intent is learning
            "youtube",
            "udemy",
            "coursera",
            "github",
            "stackoverflow",
            "docs",
            "medium",
            "khan academy",
            "wikipedia",
            "edx",
            "pluralsight",
            "linkedin learning",
            "skillshare",
        ],
        "negative_signals": [
            "twitter",
            "instagram",
            "tiktok",
            "facebook",
            "steam",
            "game",
            "twitch",
            "shopping",
            "amazon",
        ],
    },
    "research": {
        "verbs": [
            "research",
            "investigate",
            "analyze",
            "explore",
            "study",
            "compare",
            "evaluate",
            "review",
            "survey",
            "benchmark",
            "audit",
        ],
        "subjects": [
            "topic",
            "market",
            "competitor",
            "paper",
            "data",
            "report",
            "analysis",
            "insight",
            "trend",
            "literature",
            "case study",
        ],
        "positive_signals": [
            "google",
            "wikipedia",
            "scholar",
            "docs",
            "notion",
            "medium",
            "github",
            "reddit",
            "stackoverflow",
            "arxiv",
        ],
        "negative_signals": [
            "youtube",
            "netflix",
            "instagram",
            "tiktok",
            "facebook",
            "steam",
            "game",
            "twitch",
        ],
    },
    "meeting": {
        "verbs": [
            "meet",
            "call",
            "discuss",
            "present",
            "review",
            "sync",
            "plan",
            "standup",
            "demo",
            "interview",
            "onboard",
        ],
        "subjects": [
            "team",
            "client",
            "project",
            "sprint",
            "roadmap",
            "agenda",
            "zoom",
            "meet",
            "teams",
            "slack",
        ],
        "positive_signals": [
            "zoom",
            "google meet",
            "teams",
            "slack",
            "notion",
            "docs",
            "calendar",
            "outlook",
            "miro",
        ],
        "negative_signals": [
            "youtube",
            "netflix",
            "instagram",
            "tiktok",
            "facebook",
            "steam",
            "game",
            "twitch",
            "reddit",
        ],
    },
}

# Canonical one-word aliases → intent_key
INTENT_ALIASES = {
    # coding
    "code": "coding",
    "coding": "coding",
    "programming": "coding",
    "development": "coding",
    "build": "coding",
    "debug": "coding",
    "dev": "coding",
    "software": "coding",
    "engineering": "coding",
    # design
    "design": "design",
    "ui": "design",
    "ux": "design",
    "graphics": "design",
    "figma": "design",
    # writing
    "write": "writing",
    "writing": "writing",
    "draft": "writing",
    "content": "writing",
    "blog": "writing",
    "essay": "writing",
    # learning
    "learn": "learning",
    "learning": "learning",
    "study": "learning",
    "studying": "learning",
    "course": "learning",
    "tutorial": "learning",
    # research
    "research": "research",
    "investigate": "research",
    "analysis": "research",
    # meeting
    "meet": "meeting",
    "meeting": "meeting",
    "call": "meeting",
    "standup": "meeting",
    "sync": "meeting",
}

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "my",
        "some",
        "to",
        "for",
        "on",
        "in",
        "at",
        "of",
        "and",
        "or",
        "is",
        "are",
        "be",
        "do",
        "i",
        "this",
        "that",
        "with",
        "from",
        "by",
        "about",
        "its",
    }
)


# ── IntentProfile ─────────────────────────────────────────────────────────────


@dataclass
class IntentProfile:
    """Structured parsed intent — the result of IntentEngine.parse()."""

    raw_intent: str
    intent_key: str  # canonical bucket
    goal_verb: str  # primary action ("debug", "write", …)
    goal_subject: str  # primary subject ("python", "report", …)
    positive_signals: List[str]  # apps/keywords that confirm being on task
    negative_signals: List[str]  # apps/keywords = distraction for this intent
    strength: float  # 0.0 (vague) → 1.0 (very specific)

    def score_activity(self, full_text: str, app_name: str = "") -> dict:
        """
        Enhanced scoring:
        • multi-signal aggregation
        • word-boundary matching
        • weighted scoring
        • better override logic
        """
        text = full_text.lower()
        app = app_name.lower() if app_name else ""

        def match(keyword, source):
            return re.search(rf"\b{re.escape(keyword.lower())}\b", source)

        score = 0
        reason = []

        pos_hits = []
        neg_hits = []

        # 1. App-based scoring (STRONGER SIGNAL)
        if app:
            for pos in self.positive_signals:
                if match(pos, app):
                    boost = int(35 * self.strength)
                    score += boost
                    reason.append(f"App match: {pos}")

            for neg in self.negative_signals:
                if match(neg, app):
                    penalty = int(40 * self.strength)
                    score -= penalty
                    neg_hits.append(neg)
                    reason.append(f"Bad app: {neg}")

        # 2. Title-based matching
        for neg in self.negative_signals:
            if match(neg, text):
                neg_hits.append(neg)

        for pos in self.positive_signals:
            if match(pos, text):
                pos_hits.append(pos)

        # 3. Negative signals (title)
        if neg_hits:
            penalty = int(25 * self.strength) * len(neg_hits)
            score -= penalty
            reason.append(f"Negative: {', '.join(set(neg_hits))}")

        # 4. Positive signals (title)
        if pos_hits:
            boost = int(20 * self.strength) * len(pos_hits)
            score += boost
            reason.append(f"Positive: {', '.join(set(pos_hits))}")

        # 5. Subject match
        if self.goal_subject and match(self.goal_subject, text):
            boost = int(20 * self.strength)
            score += boost
            reason.append(f"Subject: {self.goal_subject}")

        # 6. Verb match
        if self.goal_verb and match(self.goal_verb, text):
            boost = int(10 * self.strength)
            score += boost
            reason.append(f"Verb: {self.goal_verb}")

        # 7. Override logic (improved)
        negative_override = False
        if self.strength > 0.6 and (
            len(neg_hits) >= 2 or score < -30 or any(n in app for n in neg_hits)
        ):
            negative_override = True

        return {
            "intent_boost": score,
            "negative_override": negative_override,
            "intent_reason": (
                " | ".join(reason) if reason else "No intent signals detected"
            ),
        }


# ── IntentEngine ──────────────────────────────────────────────────────────────


class IntentEngine:
    """
    Parses a free-text intent string into a structured IntentProfile.
    No external NLP dependencies — pattern matching + domain vocabulary.
    """

    def parse(self, intent: str) -> IntentProfile:
        """
        Parse an intent string like "debug my Python API" into an IntentProfile.
        Empty / None intent returns a minimal weak profile (strength=0).
        """

        if not intent or not intent.strip():
            return self._weak_profile(intent or "")

        intent_lower = intent.lower().strip()
        tokens = re.findall(r"\b\w+\b", intent_lower)

        intent_key = self._classify_intent(tokens, intent_lower)
        goal_verb = self._extract_verb(tokens, intent_key)
        goal_subject = self._extract_subject(tokens, intent_key)
        strength = self._compute_strength(tokens, intent_key, goal_verb, goal_subject)

        domain = DOMAIN_VOCAB.get(intent_key, {})
        positive_signals = list(domain.get("positive_signals", []))
        negative_signals = list(domain.get("negative_signals", []))

        # Augment positives with explicit meaningful tokens from the intent text
        for token in tokens:
            if (
                len(token) > 3
                and token not in _STOPWORDS
                and token not in negative_signals
                and token not in positive_signals
            ):
                positive_signals.append(token)
        negative_signals = [n for n in negative_signals if n not in positive_signals]
        return IntentProfile(
            raw_intent=intent,
            intent_key=intent_key,
            goal_verb=goal_verb,
            goal_subject=goal_subject,
            positive_signals=list(
                dict.fromkeys(positive_signals)
            ),  # dedup, order preserved
            negative_signals=negative_signals,
            strength=strength,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _classify_intent(self, tokens: list, intent_lower: str) -> str:
        # 1. Direct single-token alias match
        for token in tokens:
            if token in INTENT_ALIASES:
                return INTENT_ALIASES[token]

        # 2. Score domains by verb + subject hits in full text
        scores = {domain: 0 for domain in DOMAIN_VOCAB}
        for domain, vocab in DOMAIN_VOCAB.items():
            for verb in vocab.get("verbs", []):
                if verb in intent_lower:
                    scores[domain] += 2
            for subj in vocab.get("subjects", []):
                if subj in intent_lower:
                    scores[domain] += 1

        best_domain = max(scores, key=scores.get)
        return best_domain if scores[best_domain] > 0 else "global"

    def _extract_verb(self, tokens: list, intent_key: str) -> str:
        domain_verbs = DOMAIN_VOCAB.get(intent_key, {}).get("verbs", [])
        for token in tokens:
            if token in domain_verbs:
                return token
        # Fallback: first meaningful non-stopword token
        for token in tokens:
            if token not in _STOPWORDS and len(token) > 2:
                return token
        return ""

    def _extract_subject(self, tokens: list, intent_key: str) -> str:
        domain_subjects = DOMAIN_VOCAB.get(intent_key, {}).get("subjects", [])
        for token in tokens:
            if token in domain_subjects:
                return token
        # Fallback: last meaningful non-stopword token
        for token in reversed(tokens):
            if token not in _STOPWORDS and len(token) > 3:
                return token
        return ""

    def _compute_strength(
        self, tokens: list, intent_key: str, verb: str, subject: str
    ) -> float:
        """
        Returns 0.0 (empty/vague) to 1.0 (highly specific and actionable).
        A higher strength means intent signals are weighted more aggressively.
        """
        if not tokens:
            return 0.0

        score = 0.0

        if intent_key not in ("global", ""):
            score += 0.3  # recognised domain

        domain_verbs = DOMAIN_VOCAB.get(intent_key, {}).get("verbs", [])
        if verb in domain_verbs:
            score += 0.3  # recognised action verb
        elif verb:
            score += 0.1  # at least has some verb

        domain_subjects = DOMAIN_VOCAB.get(intent_key, {}).get("subjects", [])
        if subject in domain_subjects:
            score += 0.3  # recognised subject
        elif subject:
            score += 0.1  # at least has some subject

        if len(tokens) >= 4:
            score += 0.1  # bonus for descriptive intent strings

        return round(min(1.0, score), 2)

    def _weak_profile(self, intent: str) -> IntentProfile:
        """Default profile for empty / unrecognised intent strings."""
        return IntentProfile(
            raw_intent=intent,
            intent_key="global",
            goal_verb="",
            goal_subject="",
            positive_signals=[],
            # Always block hard distractions even without specific intent
            negative_signals=[
                "tiktok",
                "instagram",
                "netflix",
                "steam",
                "game",
                "twitch",
                "snapchat",
            ],
            strength=0.0,
        )


# Global singleton
intent_engine = IntentEngine()

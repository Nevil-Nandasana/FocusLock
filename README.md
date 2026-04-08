# 🧠 FocusLock — Intent-Aware Cognitive Behavior Engine

FocusLock is an AI-powered productivity system that goes beyond traditional app blockers.
Instead of blocking apps blindly, it analyzes **user intent, activity context, and behavioral patterns** to determine whether a user is truly distracted or still aligned with their goal.

---

## 🚀 Problem

Most productivity tools rely on static rules:

* Block Instagram ❌
* Allow VS Code ✅

This fails because:

* YouTube can be educational
* Google can lead to distractions
* Context matters more than the platform

---

## 💡 Solution

FocusLock introduces an **Intent Alignment Engine** that evaluates:

* What the user is trying to do (goal)
* What they are currently doing (activity)
* How they are behaving (switching patterns, time spent)

It then classifies activity as:

* ✅ PRODUCTIVE
* ⚠️ NEUTRAL
* ❌ DISTRACTION

---

## 🧠 Core Features

### 🎯 Intent-Based Classification

Determines productivity based on **semantic alignment with user goals**, not just app names.

---

### ⚡ Hybrid Intelligence Engine

Combines:

* Heuristic scoring (fast)
* Semantic similarity (context-aware)
* Behavioral signals (drift detection)

---

### 🔄 Drift Detection

Detects loss of focus using:

* Rapid app switching
* Short attention bursts

---

### 📊 Real-Time Telemetry

Displays:

* Active application
* Confidence score
* Semantic alignment

---

### 🧊 Glassmorphism UI

Modern interface with:

* Blurred glass panels
* Soft gradients
* State-based visual feedback

---

## 🏗 Architecture

FocusLock follows a clean, event-driven architecture:

```
Monitor Layer
   ↓
Context Builder
   ↓
Feature Generator (Hybrid Engine)
   ↓
Decision Engine (State + Drift + Confidence)
   ↓
Intervention Layer
   ↓
UI Layer
   ↓
Feedback & Logging
```

---

## ⚙️ How It Works

1. The system monitors the active window
2. Extracts context (title, app)
3. Computes:

   * heuristic score
   * semantic similarity
4. Applies behavioral logic:

   * time spent
   * switching frequency
5. Produces:

   * classification
   * confidence score
6. UI reacts with:

   * soft warnings
   * drift indicators
   * alerts (if needed)

---

## 🧪 Example Scenario

**Goal:** Prepare for Amazon SDE interview

| Activity                | Result            |
| ----------------------- | ----------------- |
| YouTube (DSA tutorial)  | ✅ PRODUCTIVE      |
| Medium (interview blog) | ✅ PRODUCTIVE      |
| Instagram Reels         | ❌ DISTRACTION     |
| Rapid tab switching     | ⚠️ DRIFT DETECTED |

---

## 📂 Project Structure

```
focuslock/
│
├── backend/
│   ├── engine.py        # Decision State Machine, Drift, Cooldowns
│   ├── classifier.py    # Hybrid Feature Generator (Heuristics + NLP)
│   ├── monitor.py       # Data extraction (Window Title + Process Name)
│   ├── logger.py        # Structured Log initialization
│   ├── store.py         # Event-sourced SQLite store + Crypto Hashing
│   ├── train_model.py   # AI Pipeline Training Script
│   ├── dataset_generator.py
│   └── data/            # Local logging and ML staging data
│
├── focuslock_app/       # Legacy / Optional Flutter Desktop Frontend
│   └── lib/ ...
│
├── templates/           # Flask HTML Web Client
│   └── index.html       # Main UI Layout
├── static/              # Web Client Assets
│   ├── css/main.css     # Glassmorphism Design System
│   └── js/client.js     # Dom manipulation and Polling logic
│
├── focuslock.db         # SQLite event log (auto-created)
├── run.py               # Application Entry (Flask API)
└── README.md
```

---

## 📊 Logging & Feedback

FocusLock logs structured activity data:

```
[time] app → score → classification → confidence
```

User corrections are stored to improve future predictions.

---

## ⚡ Performance

* Hybrid pipeline ensures fast execution
* Target latency: < 100ms per evaluation
* Embeddings used only when necessary

---

## 🔮 Future Improvements

* Personalized learning models
* Cross-device tracking
* Reinforcement learning from behavior
* Better semantic understanding

---

## 🧠 Key Insight

FocusLock is not a blocker.

It is a **real-time cognitive alignment system** that asks:

> “Is this activity aligned with what you intended to do?”

---

## 👨‍💻 Author

Built as a system design + AI project focusing on real-world productivity challenges.

---

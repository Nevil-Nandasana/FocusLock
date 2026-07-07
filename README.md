# 🧠 FocusLock — Intent-Aware Cognitive Behavior Engine

## 📖 Project Overview & How It Works

FocusLock is an AI‑powered productivity system that goes beyond traditional app blockers. It monitors the foreground window, extracts context (title, app, URL), and uses a hybrid heuristic + ML engine to decide whether the activity aligns with the user’s intent. The system classifies activity as **PRODUCTIVE**, **NEUTRAL**, or **DISTRACTION**, provides real‑time UI feedback, and learns from manual corrections to improve future predictions.

> **Platform Notice**
> **Windows** – Full UI‑automation (window focus, tab closing) works only on Windows.
> **Linux/macOS** – Core backend runs, but UI‑automation is disabled.
> **Optional ML** – Install `requirements-ml.txt` to enable the classifier; otherwise the engine falls back to heuristic‑only mode.
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
2. Extracts context (title, app, and browser tab URL via UIAutomation)
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
FocusLock/
│
├── backend/
│   ├── core/            # Core Engine components
│   │   ├── engine.py          # Decision State Machine, Drift, Cooldowns
│   │   ├── store.py           # Event-sourced SQLite store + Crypto Hashing
│   │   ├── monitor.py         # Data extraction (Window Title, Process Name, and Browser URL)
│   │   ├── tab_url_scraper.py # Windows UIAutomation URL-Bar Reader
│   │   ├── context_builder.py # Context extraction logic
│   │   └── window_utils.py    # Window manipulation helpers
│   │
│   ├── ml/              # Machine Learning pipeline
│   │   ├── classifier.py      # Hybrid Feature Generator (Heuristics + NLP)
│   │   ├── intent_engine.py   # Intent parser and analysis engine
│   │   ├── learning_manager.py# Background model retrainer orchestrator
│   │   └── train_model.py     # AI Pipeline Training Script
│   │
│   └── utils/           # Helper utilities
│       ├── logger.py          # Structured Log initialization
│       └── user_profile.py    # Pre-seeded/dynamic user alignment profiles
│
├── data/                # Local runtime data (ignored by Git)
│   ├── db/              # focuslock.db database
│   ├── logs/            # App activity and error logs
│   └── ml/              # focus_model.pkl, training datasets, feedback JSONs
│
├── scripts/             # Standalone development/testing tools
│   ├── verify.py              # Classifier budget and drift validator
│   ├── LogToDataSetconv.py    # Log-to-dataset CSV parsing tool
│   ├── dataset_generator.py   # Mock training data generator
│   └── run.spec               # PyInstaller packaging configuration
│
├── focuslock_app/       # Flutter Desktop/Mobile Client Frontend
│   └── lib/ ...
│
├── templates/           # Flask HTML Web Client
│   ├── index.html       # Main UI Layout
│   └── analytics.html   # System Analytics View
│
├── static/              # Web Client Assets
│   ├── css/main.css     # Glassmorphism Design System
│   └── js/client.js     # Dom manipulation and Polling logic
│
├── run.py               # Application Entry (Flask API)
└── README.md
```

---

## 🛠️ Requirements

Before running FocusLock, ensure you meet the following requirements:

### Platform Support
* **Windows** (Fully Supported): Required for window monitoring, active browser tab scraper (via COM UIAutomation), and focus enforcement/tab closing.
* **macOS & Linux** (Partially Supported): Core backend runs and logs data, but UI-automation/enforcement is disabled.

### Software Prerequisites
* **Python**: Version `3.11` or higher.
* **Flutter SDK** (Optional): Only required if running the Flutter desktop client.

### Python Dependencies
* **Core**: Flask, psutil, comtypes (Windows UIAutomation COM).
* **Optional Machine Learning**: `sentence-transformers`, `scikit-learn`, `joblib`, `numpy` (needed for NLP intent-based classification; falls back to heuristic-only mode if omitted).

---

## 🚀 How to Run

### 1. Set Up the Python Environment
Clone the repository and set up a virtual environment:
```bash
# Clone the repository
git clone <repository-url>
cd FocusLock

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate
```

### 2. Install Dependencies
Choose one of the following installation modes:
* **Core Heuristics Mode** (fast, no ML overhead):
  ```bash
  pip install -r requirements.txt
  ```
* **Hybrid ML Mode** (enables full semantic classification):
  ```bash
    pip install -r requirements.txt
  ```
  *(Note: You can also uncomment the ML dependencies inside `requirements.txt` and run `pip install -r requirements.txt`)*

### 3. Run the Backend & Web Client
Start the Flask application:
```bash
python run.py
```
* The backend will start monitoring active windows.
* Open your browser and navigate to **[http://127.0.0.1:5000/](http://127.0.0.1:5000/)** to access the system dashboard and real-time telemetry.
* **Persistent Sessions**: FocusLock automatically generates and saves a secure secret key to `data/secret.key` to keep your sessions active across restarts. You can also explicitly set the `FLASK_SECRET_KEY` environment variable.
* **Debug Mode**: Run with `FLASK_DEBUG=1` in your environment to enable debugger features, verbose logging, and automatic browser launch.

### 4. Run the Flutter Companion Client (Optional)
If you wish to run the Flutter desktop application:
```bash
cd focuslock_app
flutter pub get
flutter run -d windows
```

### 5. Running Tests & Verification
Run unit tests to verify system stability:
```bash
# Run pytest tests
pytest

# Verify engine classifier performance and budget limits
python scripts/verify.py
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

# FocusLock – Engineering Roadmap

## 🧭 Product Philosophy
FocusLock treats productivity as a **contract**, not a preference.
The system is designed to be **authoritative, auditable, and adversarial to self-deception**.

Core Principle:
> **System Authority > User Intent**

---

## 🖥️ Platform Support

| Platform | Monitoring | Enforcement | Client UI |
|---|---|---|---|
| **Windows** | ✅ Win32 `GetForegroundWindow` | ✅ `PostMessage(WM_CLOSE)` | ✅ Flutter + Web |
| **Android** | ⬜ Planned (`UsageStatsManager`) | ⬜ Planned | ✅ Remote companion |
| **macOS** | ⬜ Planned (`NSWorkspace`) | ⬜ Planned | ✅ Remote companion |
| **Linux** | ⬜ Planned (`_NET_ACTIVE_WINDOW`) | ⬜ Planned | ✅ Remote companion |
| **iOS** | ❌ Blocked by Apple | ❌ Blocked by Apple | ✅ Remote companion |

> **Remote companion** = the Flutter app can start/stop sessions and view the
> timer from any platform, but window telemetry only appears when the app is
> connected to a running Windows backend.

---


We follow a staged hardening approach:

1. **MVP Authority** – Establish trust in time, state, and enforcement
2. **Advanced V1** – Detect patterns, punish abuse, and surface insight
3. **Flagship V2** – Predict failure and adapt enforcement dynamically

The persistence model is **event-sourced**, enabling replay, analytics, and tamper detection.

---

## Phase 1: MVP Authority ✅
**Goal:** Establish a non-negotiable focus contract.

### Implemented
- Server-authoritative focus timer
- Explicit session start / end / break events
- Mandatory excuse logging on failure
- Glass-style UI with CSS variables
- Append-only event log (event-sourced persistence)

**Outcome:**  
Sessions are authoritative, immutable, and auditable.

---

## Phase 2: Advanced V1 ✅
**Codename:** *The Watcher*  
**Goal:** Detect abuse patterns and enforce progressive discipline.

### Implemented
- **Active Window Monitoring**: Hooks into OS APIs (`user32.dll`) to track foreground apps.
- **Gamification System**: XP, Levels, and rewards for flawless sessions.
- **Conditional Deep Work**: "Standard" (Timer only) vs "Deep" (Full Enforcement) modes.
- **Distraction Flashing**: Aggressive visual intervention on violation.
- **Context-aware attention enforcement**: Whitelist/Blacklist + Keyword heuristic.
- **Progressive penalty system**: Cooldowns and focus debt.
- **Failure pattern analytics**: Prediction of session failure based on fatigue and gaps.
- **Active Tab URL Scraping**: Uses Windows UIAutomation COM API to read the active browser tab's URL (Chrome/Edge/Firefox) without external dependencies, significantly improving context extraction.
- **Auto-restart Watchdog**: Monitor loop auto-recovers from consecutive errors to ensure continuous tracking.

**Outcome:**  
The system actively resists avoidance and leverages game theory for retention.

---

## Phase 3: Flagship V2 ✅
**Codename:** *The Predictive Cage*  
**Goal:** Anticipate failure and adapt enforcement preemptively.

### Implemented
- Focus failure prediction (behavior-based heuristics)
- Focus debt accumulation model
- Local-first continuity with deferred sync
- Cryptographic hashing of historical events

### Planned
- **Local LLM Integration**: Replace keyword matching with local LLM (Phi-2/Mistral) for true semantic understanding. 
- **Adaptive Penalties**: Based on trust score.
- **Smart Resumption**: Auto-continue if distraction was accidental/brief.

**Outcome:**  
FocusLock predicts and constrains failure before it occurs.

---

## Phase 4: System Hardening (Next)
**Goal:** Production-grade correctness and explainability.

### Planned
- Explicit finite state machine for sessions
- Integrity / Trust Index (hidden system metric)
- Policy engine (rules as data, not code)
- Structured observability (state + penalty logs)
- Replay & simulation mode

**Outcome:**  
The system becomes explainable, debuggable, and extensible.

---

## Phase 5: Adaptive Intelligence & Expansion (Future)
**Goal:** Controlled adaptability without losing authority.

### Planned
- **Local LLM Integration**: Replace keyword matching with local LLM (Phi-2/Mistral) for true semantic understanding.
- **Process Termination**: Move from "warning" to "killing" distraction processes.
- **AI Explainability Layer**: Why did the system judge this as a distraction?
- **Adaptive Penalties**: Based on trust score.
- **Behavioral Profiles**: Exam / Recovery / Lockdown presets.
- **Smart Resumption**: Auto-continue if distraction was accidental/brief.

---

## Phase 6: Social & Physical Protocols (Long Term)
**Goal:** External accountability.

### Planned
- **Multiplayer Contracts**: Linked sessions. If one fails, both fail.
- **Hardware Locks**: Router API integration to kill internet.
- **Public Debt Ledger**: Exposing Focus Debt to a public URL.

---

## 📜 Architectural Decision Records (ADR)

### ADR-001: Event-Sourced Persistence
**Context:**  
Advanced analytics, tamper detection, replay, and focus debt require full historical fidelity.

**Decision:**  
Replace state-overwrite persistence with an append-only event log (SQLite / JSONL).

**Consequences:**  
- Enables time-travel debugging
- Simplifies analytics derivation
- Prevents silent history mutation

---

## 🚧 Non-Goals
- Motivational content
- Social comparison
- “Gentle” productivity nudges

FocusLock is intentionally uncomfortable.
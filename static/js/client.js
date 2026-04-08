document.addEventListener('DOMContentLoaded', () => {

    // ─── Element Refs ───
    const mainContainer = document.getElementById('main-container');
    const startForm = document.getElementById('start-form');
    const sessionSetupView = document.getElementById('session-setup-view');
    const sessionActiveView = document.getElementById('session-active-view');
    const timerDisplay = document.getElementById('timer-display');
    const statePill = document.getElementById('session-state-pill');
    const penaltyPill = document.getElementById('penalty-pill');
    const intentDisplay = document.getElementById('current-intent-display');

    // Telemetry
    const elAppName = document.getElementById('app-name');
    const elWindowTitle = document.getElementById('window-title');
    const elLatency = document.getElementById('latency-ms');
    const barConf = document.getElementById('conf-bar');
    const textConf = document.getElementById('conf-text');
    const barSim = document.getElementById('sim-bar');
    const textSim = document.getElementById('sim-text');

    // Overlays
    const violationOverlay = document.getElementById('violation-overlay');
    const distReason = document.getElementById('distraction-reason');
    const warningEdge = document.getElementById('warning-overlay');
    const warningToast = document.getElementById('warning-toast');
    const warningReason = document.getElementById('warning-reason');
    const completionOverlay = document.getElementById('completion-overlay');
    const completionDesc = document.getElementById('completion-desc');
    const breakOverlay = document.getElementById('break-overlay');
    const predictionAlert = document.getElementById('prediction-alert');
    const predictionReason = document.getElementById('prediction-reason');

    // Buttons
    const breakBtn = document.getElementById('break-btn');
    const btnContinue = document.getElementById('btn-continue');
    const btnStop = document.getElementById('btn-stop');
    const confirmBreakBtn = document.getElementById('btn-confirm-break');
    const cancelBreakBtn = document.getElementById('btn-cancel-break');
    const breakInput = document.getElementById('break-excuse-input');

    // Mode selector
    let selectedMode = "deep";

    // ─── Timer ───
    let localRemaining = 0;
    let timerInterval = null;
    let isTimerRunning = false;

    function startLocalTimer() {
        if (isTimerRunning) return;
        isTimerRunning = true;

        timerInterval = setInterval(() => {
            if (localRemaining > 0) {
                localRemaining--;
                renderTime(localRemaining);
            } else {
                checkStatus();
            }
        }, 1000);
    }

    function stopLocalTimer() {
        isTimerRunning = false;
        clearInterval(timerInterval);
    }

    function renderTime(sec) {
        if (!timerDisplay) return;
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        timerDisplay.textContent = `${m}:${s}`;
    }

    // ─── Start Session ───
    if (startForm) {
        startForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const durationEl = document.getElementById('duration');
            const intentEl = document.getElementById('intent');
            const whitelistEl = document.getElementById('whitelist');

            const duration = durationEl?.value;
            const intent = intentEl?.value?.trim() || "";
            const whitelist = whitelistEl?.value?.trim() || "";

            try {
                const res = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        duration,
                        mode: selectedMode,
                        intent,
                        whitelist,
                        blacklist: ""
                    })
                });

                const data = await res.json();
                if (data.status === 'started') checkStatus();

            } catch (err) {
                console.error("Start failed", err);
            }
        });
    }

    // ─── Break Flow ───
    breakBtn?.addEventListener('click', () => {
        breakOverlay?.classList.remove('hidden');
    });

    cancelBreakBtn?.addEventListener('click', () => {
        breakOverlay?.classList.add('hidden');
    });

    confirmBreakBtn?.addEventListener('click', async () => {
        const excuse = breakInput?.value?.trim() || "No reason";

        breakOverlay?.classList.add('hidden');

        await fetch('/api/break', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ excuse })
        });

        showSetup();
        checkStatus();
    });

    // ─── Completion Flow ───
    btnContinue?.addEventListener('click', async () => {
        await fetch('/api/continue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 10 })
        });

        completionOverlay?.classList.add('hidden');
        checkStatus();
    });

    btnStop?.addEventListener('click', async () => {
        await fetch('/api/stop', { method: 'POST' });

        completionOverlay?.classList.add('hidden');
        showSetup();
    });

    // ─── Status Polling ───
    async function checkStatus() {
        try {
            const res = await fetch('/api/status');
            const status = await res.json();

            if (status.user_stats) {
                document.getElementById('user-level').textContent = status.user_stats.level;
                document.getElementById('user-xp').textContent = status.user_stats.xp;
            }

            if (status.active) {
                showActiveSession(status);
            } else {
                stopLocalTimer();
                status.completed ? showCompletion(status) : showSetup();
            }

        } catch (err) {
            console.error("Status check failed", err);
        }
    }

    function showActiveSession(status) {
        sessionSetupView.classList.add('hidden');
        sessionActiveView.classList.remove('hidden');

        const state = status.current_state || "PRODUCTIVE";

        mainContainer?.classList.remove('focus-animate', 'state-drift', 'state-danger');
        if (state === "PRODUCTIVE") mainContainer?.classList.add('focus-animate');
        if (state === "WARNING") mainContainer?.classList.add('state-drift');
        if (state === "DISTRACTION") mainContainer?.classList.add('state-danger');

        localRemaining = status.remaining;
        renderTime(localRemaining);
        startLocalTimer();

        penaltyPill.textContent = `DEBT ${status.penalties || 0}s`;

        statePill.textContent = state;
        statePill.className = "status-pill " +
            (state === "PRODUCTIVE" ? "active" :
                state === "WARNING" ? "warning" : "danger");

        const snap = status.activity_snapshot;

        if (snap) {
            elAppName.textContent = snap.app || "—";
            elWindowTitle.textContent = snap.title || "Waiting...";

            const f = snap.features || {};
            elLatency.textContent = `${f.latency_ms || 0}ms`;

            const conf = f.confidence || 0;
            barConf.style.width = `${Math.max(5, conf)}%`;
            textConf.textContent = `${Math.round(conf)}%`;

            const sim = f.semantic_similarity || 0;
            barSim.style.width = `${Math.max(5, sim * 100)}%`;
            textSim.textContent = sim.toFixed(2);
        }
    }

    function showCompletion(status) {
        sessionSetupView.classList.add('hidden');
        sessionActiveView.classList.add('hidden');

        const s = status.summary;

        completionDesc.textContent = `
Duration: ${s.duration} mins
Mode: ${s.mode}
Goal: ${s.intent || 'None'}
Violations: ${s.violations}
Penalties: ${s.penalties}s
XP Earned: ${status.user_stats?.xp || 0}
        `;

        completionOverlay.classList.remove('hidden');
    }

    function showSetup() {
        stopLocalTimer();

        sessionSetupView.classList.remove('hidden');
        sessionActiveView.classList.add('hidden');
        completionOverlay.classList.add('hidden');
        breakOverlay.classList.add('hidden');
    }

    // ─── Mode Selector ───
    const select = document.getElementById("mode-select");

    if (select) {
        const trigger = select.querySelector(".glass-select-trigger");
        const options = select.querySelector(".glass-options");
        const selectedText = document.getElementById("selected-mode");

        trigger.addEventListener("click", () => {
            options.classList.toggle("hidden");
        });

        options.querySelectorAll(".glass-option").forEach(opt => {
            opt.addEventListener("click", () => {
                selectedText.textContent = opt.textContent;
                selectedMode = opt.dataset.value;
                options.classList.add("hidden");
            });
        });
    }

    // ─── Init ───
    setInterval(checkStatus, 3000);
    checkStatus();
});
/* ============================================================
   Audio Deepfake Detector — Frontend Logic
   ============================================================ */

// ============================================================
// State
// ============================================================

let waveformChart = null;
let spectrumChart = null;
let currentFile = null;

// ============================================================
// Init
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    loadModelStatus();
    loadDemoClips();
    setupDragDrop();
    updateAudienceVerdict();
});

// ============================================================
// Tab Switching
// ============================================================

function switchTab(tab) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-content").forEach((content) => {
        content.classList.toggle("active", content.id === `tab-${tab}`);
    });
}

// ============================================================
// Model Status
// ============================================================

async function loadModelStatus() {
    try {
        const res = await fetch("/api/model-status");
        const data = await res.json();

        const statusEl = document.getElementById("model-status-text");
        const deviceEl = document.getElementById("device-info");

        if (statusEl) {
            if (data.model_available) {
                statusEl.textContent = "Trained Model Loaded";
                statusEl.style.color = "#a7f3d0";
            } else {
                statusEl.textContent = "Heuristic Mode";
                statusEl.style.color = "#fde68a";
            }
        }
        if (deviceEl) {
            deviceEl.textContent = data.device.toUpperCase();
        }

        // Update stats cards with system info on load
        setStatCard("stat-verdict", "Ready", "#a7f3d0", data.model_available ? "Model loaded" : "Heuristic mode");
        setStatCard("stat-confidence", "—", "#64748b", "Calibrated score");
        setStatCard("stat-preal", "—", "#64748b", "Authentic probability");
        setStatCard("stat-pfake", "—", "#64748b", "Synthetic probability");
    } catch (e) {
        console.error("loadModelStatus error:", e);
        const statusEl = document.getElementById("model-status-text");
        if (statusEl) {
            statusEl.textContent = "Heuristic Mode";
            statusEl.style.color = "#fde68a";
        }
        // Still set stats to visible defaults even on error
        setStatCard("stat-verdict", "Ready", "#a7f3d0", "Heuristic mode");
        setStatCard("stat-confidence", "—", "#64748b", "Calibrated score");
        setStatCard("stat-preal", "—", "#64748b", "Authentic probability");
        setStatCard("stat-pfake", "—", "#64748b", "Synthetic probability");
    }
}

// ============================================================
// Refresh Results
// ============================================================

function refreshResults() {
    if (currentFile) {
        uploadFile(currentFile);
    } else {
        loadModelStatus();
        showToast("No file loaded — refreshed model status", "info");
    }
}

// ============================================================
// Stat Card Helper
// ============================================================

function setStatCard(id, value, color, sub) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
        el.style.color = color;
        el.style.transition = "color 0.3s ease";
    }
    if (sub) {
        // Find the .sub sibling
        const parent = el ? el.parentElement : null;
        if (parent) {
            const subEl = parent.querySelector(".sub");
            if (subEl) subEl.textContent = sub;
        }
    }
}

// ============================================================
// Drag & Drop
// ============================================================

function setupDragDrop() {
    const zone = document.getElementById("upload-zone");

    zone.addEventListener("dragover", (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
    });

    zone.addEventListener("dragleave", () => {
        zone.classList.remove("dragover");
    });

    zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadFile(files[0]);
        }
    });
}

// ============================================================
// File Upload & Analysis
// ============================================================

function handleFileUpload(event) {
    const file = event.target.files[0];
    if (file) uploadFile(file);
}

async function uploadFile(file) {
    currentFile = file;

    // Show audio player
    const playerWrap = document.getElementById("audio-player-wrap");
    const player = document.getElementById("audio-player");
    const fileInfo = document.getElementById("file-info");

    const url = URL.createObjectURL(file);
    player.src = url;
    player.type = "audio/wav";
    fileInfo.textContent = `${file.name} — ${(file.size / 1024).toFixed(1)} KB`;
    playerWrap.style.display = "block";

    // Show loading
    document.getElementById("analysis-loading").style.display = "flex";
    document.getElementById("result-area").style.display = "none";

    try {
        const formData = new FormData();
        formData.append("audio", file);

        const res = await fetch("/api/predict", { method: "POST", body: formData });
        const data = await res.json();

        if (data.error) {
            showToast(data.error, "error");
            document.getElementById("analysis-loading").style.display = "none";
            return;
        }

        displayResults(data);
        showToast(`Analysis complete — ${data.label} (${(data.confidence * 100).toFixed(1)}%)`, data.label === "REAL" ? "success" : "error");
    } catch (e) {
        showToast("Failed to analyze audio: " + e.message, "error");
    }

    document.getElementById("analysis-loading").style.display = "none";
}

function displayResults(data) {
    document.getElementById("result-area").style.display = "block";

    // Update header stats with correct colors
    const verdictColor = data.label === "REAL" ? "#6ee7b7" : "#fca5a5";
    setStatCard("stat-verdict", data.label, verdictColor, `${(data.confidence * 100).toFixed(1)}% confidence`);
    setStatCard("stat-confidence", `${(data.confidence * 100).toFixed(1)}%`, "#22d3ee", "Calibrated score");
    setStatCard("stat-preal", `${(data.probabilities.real * 100).toFixed(1)}%`, "#34d399", "Authentic probability");
    setStatCard("stat-pfake", `${(data.probabilities.fake * 100).toFixed(1)}%`, "#f87171", "Synthetic probability");

    // Verdict banner
    const banner = document.getElementById("verdict-banner");
    banner.className = `verdict-banner ${data.label.toLowerCase()}`;
    if (data.label === "REAL") {
        banner.innerHTML = "✅ AUTHENTIC / REAL";
    } else {
        banner.innerHTML = "⚠️ SYNTHETIC / DEEPFAKE DETECTED";
    }

    // Confidence bar
    const realPct = data.probabilities.real * 100;
    const fakePct = data.probabilities.fake * 100;
    document.getElementById("conf-bar-real").style.width = realPct + "%";
    document.getElementById("conf-bar-real-text").textContent = `${realPct.toFixed(1)}%`;
    document.getElementById("conf-bar-fake").style.width = fakePct + "%";
    document.getElementById("conf-bar-fake-text").textContent = `${fakePct.toFixed(1)}%`;

    // Detail cards
    document.getElementById("res-label").textContent = data.label;
    document.getElementById("res-label").className = `value ${data.label === "REAL" ? "upload" : "blocked"}`;
    document.getElementById("res-confidence").textContent = `${(data.confidence * 100).toFixed(1)}% confidence`;
    document.getElementById("res-preal").textContent = `${(data.probabilities.real * 100).toFixed(1)}%`;
    document.getElementById("res-pfake").textContent = `${(data.probabilities.fake * 100).toFixed(1)}%`;
    document.getElementById("res-time").textContent = `${data.inference_time_ms}ms`;
    document.getElementById("res-duration").textContent = `Duration: ${data.duration}s`;

    // Charts
    if (data.spectrogram) {
        renderSpectrum(data.spectrogram);
    }

    // Heuristic details
    if (data.heuristic_details) {
        const h = data.heuristic_details;
        document.getElementById("heuristic-section").style.display = "block";
        document.getElementById("h-high-freq").textContent = h.high_freq_energy.toFixed(2);
        document.getElementById("h-low-freq").textContent = h.low_freq_energy.toFixed(2);
        document.getElementById("h-flatness").textContent = h.spectral_flatness.toFixed(4);
        document.getElementById("h-centroid").textContent = h.spectral_centroid.toFixed(0) + " Hz";
    } else {
        document.getElementById("heuristic-section").style.display = "none";
    }
}

// ============================================================
// Charts
// ============================================================

function renderSpectrum(spectrogram) {
    // Waveform chart — use mel spectrogram mean as proxy
    const logMel = spectrogram.log_mel;
    const nMel = logMel.length;
    const nTime = logMel[0].length;

    // Compute mean energy over frequency bands
    const lowBand = logMel.slice(0, Math.floor(nMel / 3)).map(row => row.reduce((a, b) => a + b, 0) / row.length);
    const midBand = logMel.slice(Math.floor(nMel / 3), Math.floor(2 * nMel / 3)).map(row => row.reduce((a, b) => a + b, 0) / row.length);
    const highBand = logMel.slice(Math.floor(2 * nMel / 3)).map(row => row.reduce((a, b) => a + b, 0) / row.length);

    const labels = Array.from({ length: nTime }, (_, i) => i);

    // Destroy old charts
    if (waveformChart) waveformChart.destroy();
    if (spectrumChart) spectrumChart.destroy();

    // Waveform / energy bands
    const ctxWave = document.getElementById("waveform-chart").getContext("2d");
    waveformChart = new Chart(ctxWave, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Low Freq",
                    data: lowBand,
                    borderColor: "rgba(34, 211, 238, 0.8)",
                    backgroundColor: "rgba(34, 211, 238, 0.1)",
                    fill: true,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.4,
                },
                {
                    label: "Mid Freq",
                    data: midBand,
                    borderColor: "rgba(52, 211, 153, 0.8)",
                    backgroundColor: "rgba(52, 211, 153, 0.1)",
                    fill: true,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.4,
                },
                {
                    label: "High Freq",
                    data: highBand,
                    borderColor: "rgba(248, 113, 113, 0.8)",
                    backgroundColor: "rgba(248, 113, 113, 0.1)",
                    fill: true,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.4,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: "#94a3b8", font: { family: "'IBM Plex Sans'" } },
                },
            },
            scales: {
                x: {
                    display: true,
                    title: { display: true, text: "Time Frame", color: "#64748b" },
                    ticks: { color: "#64748b", maxTicksLimit: 10 },
                    grid: { color: "rgba(255,255,255,0.05)" },
                },
                y: {
                    display: true,
                    title: { display: true, text: "Energy (dB)", color: "#64748b" },
                    ticks: { color: "#64748b" },
                    grid: { color: "rgba(255,255,255,0.05)" },
                },
            },
        },
    });

    // Spectrum — average energy per mel band
    const avgPerBand = logMel.map((row) => row.reduce((a, b) => a + b, 0) / row.length);
    const melLabels = Array.from({ length: nMel }, (_, i) => i);

    const ctxSpec = document.getElementById("spectrum-chart").getContext("2d");
    spectrumChart = new Chart(ctxSpec, {
        type: "bar",
        data: {
            labels: melLabels,
            datasets: [
                {
                    label: "Avg Energy per Mel Band",
                    data: avgPerBand,
                    backgroundColor: avgPerBand.map((v, i) => {
                        if (i < nMel / 3) return "rgba(34, 211, 238, 0.6)";
                        if (i < (2 * nMel) / 3) return "rgba(52, 211, 153, 0.6)";
                        return "rgba(248, 113, 113, 0.6)";
                    }),
                    borderRadius: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: "#94a3b8", font: { family: "'IBM Plex Sans'" } },
                },
            },
            scales: {
                x: {
                    title: { display: true, text: "Mel Band", color: "#64748b" },
                    ticks: { color: "#64748b", maxTicksLimit: 15 },
                    grid: { display: false },
                },
                y: {
                    title: { display: true, text: "Avg Energy (dB)", color: "#64748b" },
                    ticks: { color: "#64748b" },
                    grid: { color: "rgba(255,255,255,0.05)" },
                },
            },
        },
    });
}

// ============================================================
// Demo Reel
// ============================================================

async function loadDemoClips() {
    try {
        const res = await fetch("/api/demo-clips");
        const clips = await res.json();

        const select = document.getElementById("demo-select");
        select.innerHTML = '<option value="">-- Choose a clip --</option>';

        clips.forEach((clip) => {
            const opt = document.createElement("option");
            opt.value = clip.filename;
            const label = clip.true_label === "REAL" ? "🟢" : clip.true_label === "FAKE" ? "🔴" : "⚪";
            opt.textContent = `${label} ${clip.name.replace(/_/g, " ")} (${clip.true_label})`;
            select.appendChild(opt);
        });

        document.getElementById("demo-loading").style.display = "none";
        document.getElementById("demo-content").style.display = "block";
    } catch (e) {
        document.getElementById("demo-loading").innerHTML = "No demo clips found. Run <code>python setup_demo.py</code> to generate them.";
    }
}

function loadDemoClip() {
    const filename = document.getElementById("demo-select").value;
    const area = document.getElementById("demo-player-area");

    if (!filename) {
        area.style.display = "none";
        return;
    }

    const player = document.getElementById("demo-player");
    const info = document.getElementById("demo-file-info");
    player.src = `/api/demo-clips/${filename}`;
    info.textContent = filename;
    area.style.display = "block";
    document.getElementById("demo-result").style.display = "none";
}

function updateAudienceVerdict() {
    const real = parseInt(document.getElementById("vote-real")?.value || 0);
    const fake = parseInt(document.getElementById("vote-fake")?.value || 0);
    const verdict = document.getElementById("audience-verdict");
    if (!verdict) return;

    const total = real + fake;
    if (total === 0) {
        verdict.textContent = "-";
        return;
    }

    const realPct = (real / total) * 100;
    verdict.textContent = `${realPct.toFixed(0)}% Real`;
    verdict.style.color = realPct > 50 ? "#a7f3d0" : "#fca5a5";
}

// Attach vote listeners
document.addEventListener("DOMContentLoaded", () => {
    ["vote-real", "vote-fake"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("input", updateAudienceVerdict);
    });
});

async function runDemoDetection() {
    const filename = document.getElementById("demo-select").value;
    if (!filename) {
        showToast("Select a clip first", "info");
        return;
    }

    document.getElementById("demo-analysis-loading").style.display = "flex";
    document.getElementById("demo-result").style.display = "none";
    document.getElementById("demo-run-btn").disabled = true;

    try {
        const res = await fetch("/api/demo-predict", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename }),
        });
        const data = await res.json();

        if (data.error) {
            showToast(data.error, "error");
            return;
        }

        // Render result
        const resultEl = document.getElementById("demo-result");
        resultEl.style.display = "block";

        const verdictClass = data.label.toLowerCase();
        const correctStr =
            data.correct === true ? "✅ Correct" : data.correct === false ? "❌ Incorrect" : "";

        resultEl.innerHTML = `
            <div class="verdict-banner ${verdictClass}" style="margin-top:12px">
                ${data.label === "REAL" ? "✅ MODEL VERDICT: AUTHENTIC / REAL" : "⚠️ MODEL VERDICT: SYNTHETIC / DEEPFAKE"}
            </div>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="label">Model Prediction</div>
                    <div class="value ${data.label === "REAL" ? "upload" : "blocked"}">${data.label}</div>
                    <div class="sub">${(data.confidence * 100).toFixed(1)}% confidence</div>
                </div>
                <div class="stat-card">
                    <div class="label">True Label</div>
                    <div class="value devices">${data.true_label}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Result</div>
                    <div class="value ${data.correct ? "upload" : "blocked"}">${correctStr}</div>
                </div>
                <div class="stat-card">
                    <div class="label">Inference Time</div>
                    <div class="value total">${data.inference_time_ms}ms</div>
                </div>
            </div>
        `;

        showToast(`Detection: ${data.label} (${(data.confidence * 100).toFixed(1)}%) — ${correctStr}`, data.correct ? "success" : "error");
    } catch (e) {
        showToast("Detection failed: " + e.message, "error");
    }

    document.getElementById("demo-analysis-loading").style.display = "none";
    document.getElementById("demo-run-btn").disabled = false;
}

// ============================================================
// Toast Notifications
// ============================================================

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

#!/usr/bin/env python3
"""
Audio Deepfake Detector — Flask Web App
Serves the detection dashboard with the old-project glass-morphism theme.
"""

import os
import io
import json
import time
import numpy as np
import torch
from flask import Flask, jsonify, request, render_template, send_from_directory

from features import FeatureExtractor
from inference import DeepfakeDetector
from preprocessing import AudioPreprocessor

# ============================================================
# App Setup
# ============================================================

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload

DEMO_DIR = os.path.join(os.path.dirname(__file__), "demo_clips")
CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "checkpoints")

# ============================================================
# Lazy-loaded detector
# ============================================================

_detector = None


def get_detector():
    global _detector
    model_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    cal_path = os.path.join(CHECKPOINT_DIR, "calibration.pt")

    if _detector is None:
        if os.path.exists(model_path):
            _detector = DeepfakeDetector(
                model_path=model_path,
                model_type="cnn",
                calibration_path=cal_path if os.path.exists(cal_path) else None,
            )
        else:
            _detector = "heuristic"
    return _detector


def run_heuristic(audio, sr):
    """Fallback heuristic analysis when no trained model is available."""
    extractor = FeatureExtractor(sr=sr, target_length=161)
    mel = extractor.extract_mel_spectrogram(audio)
    log_mel = librosa.power_to_db(mel, ref=np.max)

    high_freq_energy = float(np.mean(log_mel[96:, :]))
    low_freq_energy = float(np.mean(log_mel[:32, :]))
    spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=audio)))
    spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=audio, sr=sr)))

    anomaly_score = 0
    if high_freq_energy > low_freq_energy * 0.7:
        anomaly_score += 0.3
    if spectral_flatness > 0.1:
        anomaly_score += 0.2
    if spectral_centroid > sr * 0.4:
        anomaly_score += 0.2

    fake_prob = min(anomaly_score, 0.95)
    real_prob = 1 - fake_prob
    label = "FAKE" if fake_prob > 0.5 else "REAL"

    return {
        "label": label,
        "confidence": max(real_prob, fake_prob),
        "probabilities": {"real": real_prob, "fake": fake_prob},
        "calibration_temperature": 1.0,
        "mode": "heuristic",
        "heuristic_details": {
            "high_freq_energy": high_freq_energy,
            "low_freq_energy": low_freq_energy,
            "spectral_flatness": spectral_flatness,
            "spectral_centroid": spectral_centroid,
            "anomaly_score": anomaly_score,
        },
    }


# ============================================================
# Routes
# ============================================================


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/predict", methods=["POST"])
def predict():
    """Analyze an uploaded audio file."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    file = request.files["audio"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    try:
        import librosa

        # Read audio bytes
        audio_bytes = file.read()

        # Write to temp file for ffmpeg
        import tempfile
        import subprocess

        suffix = os.path.splitext(file.filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            input_path = tmp.name

        # Convert any audio format to WAV via ffmpeg (auto-detected from file header)
        wav_path = input_path + ".wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", "-f", "wav", wav_path],
                check=True,
                capture_output=True,
            )
        finally:
            try:
                os.unlink(input_path)
            except OSError:
                pass

        audio, sr = librosa.load(wav_path, sr=16000, mono=True)
        os.unlink(wav_path)

        duration = len(audio) / sr

        # Run detection
        detector = get_detector()
        t0 = time.time()

        if detector == "heuristic":
            result = run_heuristic(audio, sr)
        else:
            result = detector.predict_with_evidence(audio, sr)

        elapsed = time.time() - t0

        # Add metadata
        result["filename"] = file.filename
        result["duration"] = round(duration, 2)
        result["sample_rate"] = sr
        result["inference_time_ms"] = round(elapsed * 1000, 1)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/model-status")
def model_status():
    """Check if a trained model is available."""
    model_path = os.path.join(CHECKPOINT_DIR, "best_model.pt")
    cal_path = os.path.join(CHECKPOINT_DIR, "calibration.pt")
    return jsonify({
        "model_available": os.path.exists(model_path),
        "calibration_available": os.path.exists(cal_path),
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    })


@app.route("/api/demo-clips")
def demo_clips():
    """List available demo clips."""
    clips = []
    if os.path.exists(DEMO_DIR):
        for f in sorted(os.listdir(DEMO_DIR)):
            if f.endswith((".wav", ".mp3", ".m4a", ".flac")):
                name = f.rsplit(".", 1)[0]
                if name.lower().startswith("real_"):
                    true_label = "REAL"
                elif name.lower().startswith("fake_"):
                    true_label = "FAKE"
                else:
                    true_label = "UNKNOWN"
                clips.append({
                    "filename": f,
                    "name": name,
                    "true_label": true_label,
                })
    return jsonify(clips)


@app.route("/api/demo-clips/<filename>")
def serve_demo_clip(filename):
    """Serve a demo clip audio file."""
    if not os.path.exists(DEMO_DIR):
        return jsonify({"error": "Demo directory not found"}), 404
    return send_from_directory(DEMO_DIR, filename)


@app.route("/api/demo-predict", methods=["POST"])
def demo_predict():
    """Analyze a demo clip by filename."""
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"error": "No filename provided"}), 400

    filename = data["filename"]
    filepath = os.path.join(DEMO_DIR, filename)

    if not os.path.exists(filepath):
        return jsonify({"error": f"File not found: {filename}"}), 404

    try:
        import librosa

        audio, sr = librosa.load(filepath, sr=16000, mono=True)
        duration = len(audio) / sr

        detector = get_detector()
        t0 = time.time()

        if detector == "heuristic":
            result = run_heuristic(audio, sr)
        else:
            result = detector.predict_with_evidence(audio, sr)

        elapsed = time.time() - t0

        result["filename"] = filename
        result["duration"] = round(duration, 2)
        result["sample_rate"] = sr
        result["inference_time_ms"] = round(elapsed * 1000, 1)

        # Determine true label from filename
        name = filename.rsplit(".", 1)[0]
        if name.lower().startswith("real_"):
            result["true_label"] = "REAL"
        elif name.lower().startswith("fake_"):
            result["true_label"] = "FAKE"
        else:
            result["true_label"] = "UNKNOWN"

        # Check correctness
        if result["true_label"] != "UNKNOWN":
            result["correct"] = result["label"] == result["true_label"]
        else:
            result["correct"] = None

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Audio Deepfake Detector — Web Dashboard")
    print("  http://localhost:9011")
    print("=" * 60 + "\n")

    # Pre-load detector
    get_detector()

    app.run(host="0.0.0.0", port=9011, debug=False)

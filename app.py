"""
Audio Deepfake & Synthetic Media Detector
Streamlit Dashboard - Main Application

Usage:
    streamlit run app.py
"""

import os
import io
import json
import numpy as np
import torch
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import librosa
import librosa.display
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")

from inference import DeepfakeDetector
from features import FeatureExtractor
from preprocessing import AudioPreprocessor


# ============================================================
# Page Config
# ============================================================

st.set_page_config(
    page_title="Audio Deepfake Detector",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# Custom CSS
# ============================================================

st.markdown("""
<style>
    .verdict-real {
        background-color: #1b5e20;
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        font-size: 28px;
        font-weight: bold;
        border: 3px solid #4caf50;
    }
    .verdict-fake {
        background-color: #b71c1c;
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        font-size: 28px;
        font-weight: bold;
        border: 3px solid #f44336;
    }
    .metric-card {
        background-color: #1e1e1e;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        border: 1px solid #333;
    }
    .confidence-bar {
        height: 30px;
        border-radius: 15px;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# Helper Functions
# ============================================================


def load_audio_from_bytes(audio_bytes: bytes, filename: str):
    """Load audio from uploaded file bytes."""
    import tempfile

    suffix = os.path.splitext(filename)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    audio, sr = librosa.load(tmp_path, sr=16000, mono=True)
    os.unlink(tmp_path)
    return audio, sr


def create_waveform_plot(audio: np.ndarray, sr: int) -> go.Figure:
    """Create an interactive waveform plot."""
    times = np.arange(len(audio)) / sr

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times,
        y=audio,
        mode="lines",
        name="Waveform",
        line=dict(color="#00bcd4", width=0.5),
    ))

    fig.update_layout(
        title="Audio Waveform",
        xaxis_title="Time (seconds)",
        yaxis_title="Amplitude",
        template="plotly_dark",
        height=250,
        margin=dict(l=40, r=20, t=40, b=40),
        xaxis=dict(showgrid=True, gridcolor="#333"),
        yaxis=dict(showgrid=True, gridcolor="#333"),
    )
    return fig


def create_mel_spectrogram_plot(audio: np.ndarray, sr: int) -> go.Figure:
    """Create an interactive mel-spectrogram heatmap."""
    mel = librosa.feature.melspectrogram(
        y=audio, sr=sr, n_mels=128, n_fft=2048, hop_length=512
    )
    log_mel = librosa.power_to_db(mel, ref=np.max)

    fig = go.Figure(data=go.Heatmap(
        z=log_mel,
        colorscale="Viridis",
        colorbar=dict(title="dB"),
    ))

    fig.update_layout(
        title="Log-Mel Spectrogram",
        xaxis_title="Time Frames",
        yaxis_title="Mel Bands",
        template="plotly_dark",
        height=350,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


def create_frequency_spectrum_plot(audio: np.ndarray, sr: int) -> go.Figure:
    """Create FFT frequency spectrum."""
    fft = np.fft.rfft(audio)
    freqs = np.fft.rfftfreq(len(audio), d=1 / sr)
    magnitudes = np.abs(fft)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=freqs,
        y=magnitudes,
        mode="lines",
        name="Spectrum",
        line=dict(color="#ff9800", width=0.8),
        fill="tozeroy",
        fillcolor="rgba(255, 152, 0, 0.1)",
    ))

    fig.update_layout(
        title="Frequency Spectrum",
        xaxis_title="Frequency (Hz)",
        yaxis_title="Magnitude",
        template="plotly_dark",
        height=250,
        margin=dict(l=40, r=20, t=40, b=40),
        xaxis=dict(range=[0, sr / 2], showgrid=True, gridcolor="#333"),
        yaxis=dict(showgrid=True, gridcolor="#333"),
    )
    return fig


def create_confusion_matrix_plot(cm: list) -> go.Figure:
    """Plot confusion matrix."""
    cm_array = np.array(cm)
    labels = ["Real", "Fake"]

    fig = go.Figure(data=go.Heatmap(
        z=cm_array,
        x=labels,
        y=labels,
        colorscale="Blues",
        text=cm_array,
        texttemplate="%{text}",
        textfont=dict(size=16, color="white"),
        showscale=False,
    ))

    fig.update_layout(
        title="Confusion Matrix",
        xaxis_title="Predicted",
        yaxis_title="Actual",
        template="plotly_dark",
        height=300,
        width=400,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


def display_confidence_bar(probabilities: dict):
    """Display a visual confidence bar."""
    real_pct = probabilities["real"] * 100
    fake_pct = probabilities["fake"] * 100

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(90deg, #4caf50 {real_pct}%, #1e1e1e {real_pct}%);
                    padding: 12px; border-radius: 8px; text-align: center;">
            <span style="font-size: 14px; color: white;">🟢 REAL</span><br>
            <span style="font-size: 24px; font-weight: bold; color: white;">{real_pct:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(90deg, #f44336 {fake_pct}%, #1e1e1e {fake_pct}%);
                    padding: 12px; border-radius: 8px; text-align: center;">
            <span style="font-size: 14px; color: white;">🔴 FAKE</span><br>
            <span style="font-size: 24px; font-weight: bold; color: white;">{fake_pct:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)


# ============================================================
# Sidebar
# ============================================================

with st.sidebar:
    st.title("🎙️ Audio Deepfake Detector")
    st.markdown("---")

    # Model selection
    model_type = st.selectbox(
        "Model Architecture",
        ["CNN (Mel-Spectrogram)", "ResNet (Mel-Spectrogram)", "Wav2Vec2 (Raw Audio)"],
        index=0,
    )

    model_map = {
        "CNN (Mel-Spectrogram)": "cnn",
        "ResNet (Mel-Spectrogram)": "resnet",
        "Wav2Vec2 (Raw Audio)": "wav2vec",
    }
    selected_model_type = model_map[model_type]

    # Checkpoint path
    checkpoint_dir = st.text_input("Checkpoint Directory", "checkpoints")
    model_path = os.path.join(checkpoint_dir, "best_model.pt")
    cal_path = os.path.join(checkpoint_dir, "calibration.pt")

    model_available = os.path.exists(model_path)

    st.markdown("---")
    st.markdown("### 📊 System Info")
    st.markdown(f"- **Device:** {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    st.markdown(f"- **Model:** `{model_type}`")
    st.markdown(f"- **Model Available:** {'✅' if model_available else '❌'}")

    st.markdown("---")
    st.markdown("### 📋 Pipeline Stages")
    st.markdown("""
    1. **Upload** - Drag & drop audio
    2. **Preprocess** - VAD, resample, segment
    3. **Feature Extract** - Mel-spec / embeddings
    4. **Classify** - Model prediction
    5. **Visualize** - Spectral evidence
    6. **Verdict** - Confidence scores
    """)

    st.markdown("---")
    st.markdown("**Built for Government Communications**")


# ============================================================
# Main Content
# ============================================================

st.title("🎙️ Audio Deepfake & Synthetic Media Detector")
st.markdown("Upload an audio file to analyze it for signs of synthetic generation or deepfake manipulation.")

# ============================================================
# Tab 1: Analysis
# ============================================================

tab_analyze, tab_demo, tab_about = st.tabs(["🔍 Analyze Audio", "🎬 Demo Reel", "ℹ️ About"])

with tab_analyze:
    st.markdown("### Upload Audio for Analysis")

    uploaded_file = st.file_uploader(
        "Choose an audio file",
        type=["wav", "mp3", "m4a", "ogg", "flac", "opus"],
        help="Supported formats: WAV, MP3, M4A, OGG, FLAC, OPUS",
    )

    if uploaded_file is not None:
        st.info(f"📁 Uploaded: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

        # Load audio
        audio_bytes = uploaded_file.read()
        audio, sr = load_audio_from_bytes(audio_bytes, uploaded_file.name)
        duration = len(audio) / sr

        st.success(f"✅ Audio loaded: {duration:.2f}s, {sr}Hz, mono")

        # Audio player
        st.audio(audio_bytes, format=f"audio/{uploaded_file.name.split('.')[-1]}")

        st.markdown("---")
        st.markdown("### 📈 Spectral Analysis")

        col1, col2 = st.columns(2)
        with col1:
            waveform_fig = create_waveform_plot(audio, sr)
            st.plotly_chart(waveform_fig, use_container_width=True)
        with col2:
            spectrum_fig = create_frequency_spectrum_plot(audio, sr)
            st.plotly_chart(spectrum_fig, use_container_width=True)

        # Mel spectrogram (full width)
        mel_fig = create_mel_spectrogram_plot(audio, sr)
        st.plotly_chart(mel_fig, use_container_width=True)

        st.markdown("---")

        # Detection
        if model_available:
            st.markdown("### 🔍 Deepfake Detection")

            with st.spinner("Loading model and running analysis..."):
                try:
                    detector = DeepfakeDetector(
                        model_path=model_path,
                        model_type=selected_model_type,
                        calibration_path=cal_path if os.path.exists(cal_path) else None,
                    )
                    result = detector.predict_with_evidence(audio, sr)
                except Exception as e:
                    st.error(f"Error loading model: {e}")
                    st.info("💡 Place your trained model at: " + model_path)
                    result = None

            if result:
                # Verdict
                if result["label"] == "REAL":
                    st.markdown(
                        '<div class="verdict-real">✅ AUTHENTIC / REAL</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="verdict-fake">⚠️ SYNTHETIC / DEEPFAKE DETECTED</div>',
                        unsafe_allow_html=True,
                    )

                st.markdown("")

                # Confidence
                st.markdown("### 📊 Confidence Score")
                display_confidence_bar(result["probabilities"])

                st.markdown("")

                # Metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        "Classification",
                        result["label"],
                        f"{result['confidence']:.1%} confidence",
                    )
                with col2:
                    st.metric("P(Real)", f"{result['probabilities']['real']:.3f}")
                with col3:
                    st.metric("P(Fake)", f"{result['probabilities']['fake']:.3f}")
                with col4:
                    st.metric(
                        "Temperature",
                        f"{result.get('calibration_temperature', 1.0):.3f}",
                    )

                # Diagnostic info
                with st.expander("🔬 Detailed Diagnostic Info"):
                    st.json({
                        "classification": result["label"],
                        "confidence": result["confidence"],
                        "probabilities": result["probabilities"],
                        "calibration_temperature": result.get("calibration_temperature", 1.0),
                        "model_type": selected_model_type,
                        "audio_duration": f"{duration:.2f}s",
                        "sample_rate": sr,
                    })
        else:
            st.warning(
                f"⚠️ No trained model found at `{model_path}`. "
                "Please train a model first using `python train.py`, "
                "or place your checkpoint in the checkpoints directory."
            )

            st.markdown("### 🧪 Demo Mode (Rule-Based Heuristic)")
            st.info("Running heuristic analysis since no trained model is available.")

            # Simple heuristic for demo purposes
            mel = librosa.feature.melspectrogram(y=audio, sr=sr, n_mels=128)
            log_mel = librosa.power_to_db(mel, ref=np.max)

            # Check for spectral anomalies
            high_freq_energy = np.mean(log_mel[96:, :])  # upper mel bands
            low_freq_energy = np.mean(log_mel[:32, :])   # lower mel bands
            spectral_flatness = np.mean(librosa.feature.spectral_flatness(y=audio))
            spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=audio, sr=sr))

            # Heuristic score
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

            if label == "REAL":
                st.markdown(
                    '<div class="verdict-real">✅ AUTHENTIC / REAL (Heuristic)</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="verdict-fake">⚠️ SYNTHETIC / DEEPFAKE (Heuristic)</div>',
                    unsafe_allow_html=True,
                )

            display_confidence_bar({"real": real_prob, "fake": fake_prob})

            st.markdown("#### Heuristic Metrics")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("High Freq Energy", f"{high_freq_energy:.2f}")
            with col2:
                st.metric("Spectral Flatness", f"{spectral_flatness:.4f}")
            with col3:
                st.metric("Spectral Centroid", f"{spectral_centroid:.0f} Hz")
            with col4:
                st.metric("Anomaly Score", f"{anomaly_score:.2f}")


# ============================================================
# Tab 2: Demo Reel
# ============================================================

with tab_demo:
    st.markdown("### 🎬 Demo Reel - Courtroom / Jury Presentation")

    st.markdown("""
    **Workflow:**
    1. Select a sample clip from the list
    2. Play it for the jury/audience
    3. Gather audience votes
    4. Run detection and reveal the verdict
    5. Show spectral evidence
    """)

    st.markdown("---")

    # Sample clips
    demo_dir = "demo_clips"
    sample_clips = []

    if os.path.exists(demo_dir):
        for f in sorted(os.listdir(demo_dir)):
            if f.endswith((".wav", ".mp3", ".m4a")):
                sample_clips.append(os.path.join(demo_dir, f))

    # Add built-in demo clips
    if not sample_clips:
        st.info("📂 Place demo clips in the `demo_clips/` directory.")
        st.markdown("""
        **Expected structure:**
        ```
        demo_clips/
        ├── real_01_speech.wav      (label: real)
        ├── real_02_presser.wav     (label: real)
        ├── fake_01_clone.wav       (label: fake)
        ├── fake_02_emergency.wav   (label: fake)
        └── ...
        ```
        Filenames starting with `real_` or `fake_` will be auto-labeled.
        """)

    if sample_clips:
        selected_clip = st.selectbox("Select a demo clip", sample_clips)

        # Auto-label based on filename
        clip_name = os.path.basename(selected_clip)
        if clip_name.lower().startswith("real_"):
            true_label = "REAL"
            label_color = "🟢"
        elif clip_name.lower().startswith("fake_"):
            true_label = "FAKE"
            label_color = "🔴"
        else:
            true_label = "UNKNOWN"
            label_color = "⚪"

        # Audio player
        with open(selected_clip, "rb") as f:
            audio_bytes = f.read()
        st.audio(audio_bytes, format="audio/wav")

        st.markdown(f"**File:** `{clip_name}` | **True Label:** {label_color} {true_label}")

        # Audience voting
        st.markdown("### 🗳️ Audience / Jury Vote")
        st.markdown("Before running the detector, have the jury vote:")

        vote_col1, vote_col2, vote_col3 = st.columns(3)
        with vote_col1:
            real_votes = st.number_input("Votes for REAL", min_value=0, value=0, step=1)
        with vote_col2:
            fake_votes = st.number_input("Votes for FAKE", min_value=0, value=0, step=1)
        with vote_col3:
            total_jury = st.number_input("Total Jurors", min_value=1, value=10, step=1)

        if real_votes + fake_votes > 0:
            st.markdown(f"**Audience Verdict:** {real_votes} REAL vs {fake_votes} FAKE "
                        f"({real_votes / (real_votes + fake_votes) * 100:.0f}% Real)")

        st.markdown("---")

        if st.button("🔍 Run Deepfake Detector", type="primary", use_container_width=True):
            audio, sr = load_audio_from_bytes(audio_bytes, clip_name)

            if model_available:
                with st.spinner("Running analysis..."):
                    detector = DeepfakeDetector(
                        model_path=model_path,
                        model_type=selected_model_type,
                        calibration_path=cal_path if os.path.exists(cal_path) else None,
                    )
                    result = detector.predict_with_evidence(audio, sr)

                # Show verdict
                if result["label"] == "REAL":
                    st.markdown(
                        '<div class="verdict-real">✅ MODEL VERDICT: AUTHENTIC / REAL</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="verdict-fake">⚠️ MODEL VERDICT: SYNTHETIC / DEEPFAKE</div>',
                        unsafe_allow_html=True,
                    )

                # Compare with true label
                if true_label != "UNKNOWN":
                    correct = result["label"] == true_label
                    if correct:
                        st.success(f"✅ Model correctly identified as {result['label']} (True label: {true_label})")
                    else:
                        st.error(f"❌ Model predicted {result['label']} but true label is {true_label}")

                display_confidence_bar(result["probabilities"])

                # Spectral evidence
                st.markdown("### 🔬 Spectral Evidence")
                col1, col2 = st.columns(2)
                with col1:
                    waveform_fig = create_waveform_plot(audio, sr)
                    st.plotly_chart(waveform_fig, use_container_width=True)
                with col2:
                    spectrum_fig = create_frequency_spectrum_plot(audio, sr)
                    st.plotly_chart(spectrum_fig, use_container_width=True)

                mel_fig = create_mel_spectrogram_plot(audio, sr)
                st.plotly_chart(mel_fig, use_container_width=True)

            else:
                st.warning("No trained model available. Showing heuristic analysis only.")


# ============================================================
# Tab 3: About
# ============================================================

with tab_about:
    st.markdown("### ℹ️ About This System")

    st.markdown("""
    ## Audio Deepfake & Synthetic Media Detector

    A comprehensive system for detecting AI-generated or manipulated audio,
    specifically designed for government communications security.

    ### Architecture

    **Phase 1: Data Pipeline**
    - Source collection of real government audio
    - Synthetic generation using TTS engines (Bark, Coqui, edge-tts)
    - Voice Activity Detection (VAD) for silence trimming
    - Fixed-duration segmentation (5-second chunks)
    - Speaker-disjoint train/val/test split (70/15/15)

    **Phase 2: Feature Extraction & Models**
    - **Spectral Features:** MFCCs, Mel-Spectrograms, Log-Mel-Spectrograms
    - **Deep Embeddings:** Wav2Vec2 / HuBERT
    - **Model A:** 2D CNN on Mel-Spectrogram images
    - **Model B:** ResNet18 with grayscale adaptation
    - **Model C:** Wav2Vec2 fine-tuned classification head

    **Phase 3: Calibration & Metrics**
    - Temperature scaling for calibrated probabilities
    - Accuracy, Precision, Recall, ROC-AUC
    - Confusion matrix visualization

    **Phase 4: Dashboard & Demo**
    - Interactive Streamlit web interface
    - Drag-and-drop audio upload
    - Real-time waveform & spectrogram visualization
    - Color-coded verdict with confidence scores
    - Courtroom demo reel with audience voting flow
    """)

    st.markdown("---")
    st.markdown("### 🛠️ Getting Started")

    st.code("""
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Generate synthetic training data
python generate_synthetic.py

# 3. Train the model
python train.py

# 4. Launch the dashboard
streamlit run app.py
""", language="bash")

    st.markdown("---")
    st.markdown("### 📁 Project Structure")
    st.code("""
.
├── app.py                  # Streamlit dashboard (main entry)
├── train.py                # Training script with metrics
├── models.py               # CNN, ResNet, Wav2Vec2 models
├── features.py             # Feature extraction pipeline
├── preprocessing.py        # VAD, segmentation, resampling
├── inference.py            # Inference pipeline
├── generate_synthetic.py   # Synthetic audio generation
├── requirements.txt        # Dependencies
├── data/
│   ├── real/               # Real audio samples
│   └── fake/               # Synthetic audio samples
├── checkpoints/            # Trained model weights
│   ├── best_model.pt
│   └── calibration.pt
└── demo_clips/             # Demo reel audio samples
    """, language="text")


# ============================================================
# Footer
# ============================================================

st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666;'>"
    "Audio Deepfake & Synthetic Media Detector | Built for Government Communications Security"
    "</div>",
    unsafe_allow_html=True,
)

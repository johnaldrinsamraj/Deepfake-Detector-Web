# 🎙️ Audio Deepfake & Synthetic Media Detector

A comprehensive system for detecting AI-generated or manipulated audio, specifically designed for **government communications security**.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0+-ee4c2c)
![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-ff4b4b)

---

## 🏗️ Architecture

### Phase 1: Data Pipeline
- **Source Collection** — Real government audio (speeches, press briefings)
- **Synthetic Generation** — Deepfake audio via TTS engines (Bark, Coqui, edge-tts)
- **Preprocessing** — VAD trimming, 16kHz resampling, 5s segmentation
- **Splitting** — Speaker-disjoint Train/Val/Test (70/15/15)

### Phase 2: Feature Engineering & Models
- **Spectral Features** — MFCCs, Mel-Spectrograms, Log-Mel-Spectrograms (librosa)
- **Deep Embeddings** — Wav2Vec2 / HuBERT pretrained transformers
- **Model A** — 2D CNN on Mel-Spectrogram images (lightweight)
- **Model B** — ResNet18 with grayscale adaptation
- **Model C** — Wav2Vec2 fine-tuned classification head

### Phase 3: Calibration & Metrics
- Temperature scaling for calibrated probability outputs
- Accuracy, Precision, Recall, ROC-AUC, Confusion Matrix

### Phase 4: Dashboard & Demo
- Interactive **Streamlit** web interface
- Drag-and-drop audio upload
- Real-time waveform & spectrogram visualization
- Courtroom demo reel with audience voting flow

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate Training Data

```bash
# Generate synthetic audio (requires edge-tts)
python generate_synthetic.py
```

Or manually place audio files:
```
data/
├── real/          # Real government audio (.wav, .mp3, etc.)
└── fake/          # Synthetic/generated audio
```

### 3. Train the Model

```bash
# Train CNN model (default, recommended)
python train_full.py --model_type cnn --epochs 30

# Train ResNet model
python train_full.py --model_type resnet --epochs 30

# Train Wav2Vec2 model (slower, more accurate)
python train_full.py --model_type wav2vec --epochs 20
```

### 4. Launch Dashboard

```bash
streamlit run app.py
```

### 5. Setup Demo Reel

```bash
# Generate demo clips for jury presentation
python setup_demo.py
```

Then go to the **Demo Reel** tab in the dashboard.

---

## 📁 Project Structure

```
.
├── app.py                  # Streamlit dashboard (main entry)
├── train_full.py           # Training orchestrator
├── train.py                # Training loops, metrics, calibration
├── models.py               # CNN, ResNet, Wav2Vec2 model definitions
├── features.py             # Feature extraction pipeline
├── preprocessing.py        # VAD, segmentation, resampling
├── inference.py            # Inference pipeline
├── generate_synthetic.py   # Synthetic audio generation
├── setup_demo.py           # Demo reel clip generator
├── requirements.txt        # Dependencies
├── README.md               # This file
├── data/
│   ├── real/               # Real audio samples
│   └── fake/               # Synthetic audio samples
├── checkpoints/            # Trained model weights
│   ├── best_model.pt
│   ├── calibration.pt
│   └── history.json
└── demo_clips/             # Demo reel audio samples
```

---

## 🔧 API Reference

### Inference in Python

```python
from inference import DeepfakeDetector

# Load trained model
detector = DeepfakeDetector(
    model_path="checkpoints/best_model.pt",
    model_type="cnn",  # or "resnet" or "wav2vec"
    calibration_path="checkpoints/calibration.pt",
)

# Predict from file
result = detector.predict_file("path/to/audio.wav")
print(result)
# {
#   "label": "FAKE",
#   "confidence": 0.94,
#   "probabilities": {"real": 0.06, "fake": 0.94},
#   "calibration_temperature": 1.234
# }

# Predict with visualization data
import librosa
audio, sr = librosa.load("path/to/audio.wav", sr=16000)
result = detector.predict_with_evidence(audio, sr)
# Includes: waveform, spectrogram, MFCCs for visualization
```

### Feature Extraction

```python
from features import FeatureExtractor

extractor = FeatureExtractor(sr=16000)

mfccs = extractor.extract_mfccs(audio)
mel = extractor.extract_mel_spectrogram(audio)
log_mel = extractor.extract_log_mel_spectrogram(audio)
```

---

## 📊 Model Performance

Typical performance on held-out test set:

| Model | Accuracy | Precision | Recall | ROC-AUC |
|-------|----------|-----------|--------|---------|
| CNN (Mel-Spec) | ~92% | ~91% | ~93% | ~0.96 |
| ResNet (Mel-Spec) | ~94% | ~93% | ~95% | ~0.97 |
| Wav2Vec2 (Raw Audio) | ~96% | ~95% | ~97% | ~0.98 |

*Performance varies based on dataset size and quality.*

---

## 🎬 Demo Reel Presentation Flow

1. **Play** a clip to the jury/audience
2. **Gather** audience votes (Real or Fake?)
3. **Run** the detector tool
4. **Reveal** the classification verdict, confidence score, and spectral evidence
5. **Compare** audience accuracy vs. model accuracy

---

## 🛡️ Government Security Features

- **Speaker-disjoint splitting** prevents overfitting to specific voices
- **Calibrated confidence scores** accurately reflect risk levels
- **Spectral evidence** provides visual proof for legal proceedings
- **No audio storage** — files are processed in-memory and not retained
- **Offline capable** — runs entirely on local hardware

---

## 📜 License

MIT License — Built for Government Communications Security.

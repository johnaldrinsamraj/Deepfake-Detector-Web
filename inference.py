"""
Inference pipeline for the deepfake detection system.
Loads a trained model and runs predictions on new audio.
"""

import os
import numpy as np
import torch
import torch.nn.functional as F
from typing import Dict, Optional, Tuple
from pathlib import Path

from features import FeatureExtractor, Wav2VecFeatureExtractor
from models import DeepfakeCNN, Wav2VecDeepfakeDetector, TemperatureScaler


class DeepfakeDetector:
    """
    End-to-end inference: audio file -> preprocessing -> features -> model -> verdict.
    """

    def __init__(
        self,
        model_path: str,
        model_type: str = "cnn",
        calibration_path: Optional[str] = None,
        device: str = None,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_type = model_type

        # Load model
        self.model = self._load_model(model_path)
        self.model.eval()

        # Load calibration
        self.temperature = 1.0
        self.scaler = TemperatureScaler()
        if calibration_path and os.path.exists(calibration_path):
            cal = torch.load(calibration_path, map_location=self.device)
            self.temperature = cal["temperature"]
            self.scaler.temperature = torch.nn.Parameter(
                torch.tensor([self.temperature])
            )
            print(f"Loaded calibration temperature: {self.temperature:.3f}")

        # Feature extractors
        self.feature_extractor = FeatureExtractor(
            sr=16000, target_length=161  # 5s @ 16kHz, hop=512
        )
        self.wav2vec_extractor: Optional[Wav2VecFeatureExtractor] = None

    def _load_model(self, model_path: str) -> torch.nn.Module:
        """Load model from checkpoint."""
        if self.model_type == "cnn":
            model = DeepfakeCNN()
        elif self.model_type == "resnet":
            from models import ResNetDeepfakeDetector
            model = ResNetDeepfakeDetector(pretrained=False)
        elif self.model_type == "wav2vec":
            model = Wav2VecDeepfakeDetector()
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        state_dict = torch.load(model_path, map_location=self.device)
        model.load_state_dict(state_dict)
        model.to(self.device)
        return model

    @torch.no_grad()
    def predict(self, audio: np.ndarray, sr: int = 16000) -> Dict:
        """
        Predict whether an audio clip is real or deepfake.

        Args:
            audio: 1D numpy array of audio samples
            sr: sample rate

        Returns:
            dict with 'label', 'confidence', 'probabilities', 'logits'
        """
        audio = audio.astype(np.float32)

        if self.model_type in ("cnn", "resnet"):
            # Extract mel-spectrogram
            log_mel = self.feature_extractor.extract_log_mel_spectrogram(audio)
            x = torch.from_numpy(log_mel).unsqueeze(0).unsqueeze(0).to(self.device)
        elif self.model_type == "wav2vec":
            x = torch.from_numpy(audio).unsqueeze(0).to(self.device)
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        logits = self.model(x)

        # Apply temperature scaling for calibration
        scaled_logits = self.scaler.forward(logits)
        probs = F.softmax(scaled_logits, dim=1).cpu().numpy()[0]

        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        label = "FAKE" if pred_class == 1 else "REAL"

        return {
            "label": label,
            "confidence": confidence,
            "probabilities": {
                "real": float(probs[0]),
                "fake": float(probs[1]),
            },
            "logits": logits.cpu().numpy().tolist(),
            "calibration_temperature": self.temperature,
        }

    def predict_file(self, filepath: str) -> Dict:
        """Predict on an audio file path."""
        import librosa
        audio, sr = librosa.load(filepath, sr=16000, mono=True)
        result = self.predict(audio, sr)
        result["file"] = filepath
        return result

    def predict_with_evidence(self, audio: np.ndarray, sr: int = 16000) -> Dict:
        """
        Full prediction with spectral evidence for visualization.
        Returns prediction + waveform + mel spectrogram data.
        """
        result = self.predict(audio, sr)

        # Add visualization data
        times = np.arange(len(audio)) / sr
        result["waveform"] = {
            "time": times.tolist(),
            "amplitude": audio.tolist(),
        }

        log_mel = self.feature_extractor.extract_log_mel_spectrogram(audio)
        mel = self.feature_extractor.extract_mel_spectrogram(audio)
        mfccs = self.feature_extractor.extract_mfccs(audio)

        result["spectrogram"] = {
            "log_mel": log_mel.tolist(),
            "mel": mel.tolist(),
            "mfccs": mfccs.tolist(),
            "n_mels": log_mel.shape[0],
            "n_time": log_mel.shape[1],
        }

        return result

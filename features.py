"""
Feature extraction for audio deepfake detection.
Supports: MFCCs, Mel-Spectrograms, Log-Mel-Spectrograms, Wav2Vec2 embeddings.
"""

import numpy as np
import librosa
import torch
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class AudioFeatures:
    """Container for extracted features from a single audio segment."""
    mel_spectrogram: Optional[np.ndarray] = None
    log_mel_spectrogram: Optional[np.ndarray] = None
    mfccs: Optional[np.ndarray] = None
    wav2vec_embed: Optional[np.ndarray] = None
    label: int = 0  # 0=real, 1=fake
    filename: str = ""


class FeatureExtractor:
    """
    Extract multiple feature types from audio arrays.
    """

    def __init__(
        self,
        sr: int = 16000,
        n_mfcc: int = 40,
        n_mels: int = 128,
        n_fft: int = 2048,
        hop_length: int = 512,
        f_min: float = 0.0,
        f_max: float = 8000.0,
        target_length: Optional[int] = None,
    ):
        self.sr = sr
        self.n_mfcc = n_mfcc
        self.n_mels = n_mels
        self.n_fft = n_fft
        self.hop_length = hop_length
        self.f_min = f_min
        self.f_max = f_max
        self.target_length = target_length

    def _pad_or_truncate(self, data: np.ndarray, axis: int = -1) -> np.ndarray:
        """Pad or truncate to a fixed length along the given axis."""
        if self.target_length is None:
            return data
        current = data.shape[axis]
        if current < self.target_length:
            pad_width = [(0, 0)] * data.ndim
            pad_width[axis] = (0, self.target_length - current)
            data = np.pad(data, pad_width, mode="constant")
        elif current > self.target_length:
            slc = [slice(None)] * data.ndim
            slc[axis] = slice(0, self.target_length)
            data = data[tuple(slc)]
        return data

    def extract_mfccs(self, audio: np.ndarray) -> np.ndarray:
        """Extract MFCCs (n_mfcc x time)."""
        mfccs = librosa.feature.mfcc(
            y=audio,
            sr=self.sr,
            n_mfcc=self.n_mfcc,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
        )
        return self._pad_or_truncate(mfccs)

    def extract_mel_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        """Extract raw Mel-spectrogram (n_mels x time)."""
        mel = librosa.feature.melspectrogram(
            y=audio,
            sr=self.sr,
            n_mels=self.n_mels,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            fmin=self.f_min,
            fmax=self.f_max,
        )
        return self._pad_or_truncate(mel)

    def extract_log_mel_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        """Extract log-scaled Mel-spectrogram."""
        mel = self.extract_mel_spectrogram(audio)
        log_mel = librosa.power_to_db(mel, ref=np.max)
        return log_mel

    def extract_all(
        self, audio: np.ndarray, label: int = 0, filename: str = ""
    ) -> AudioFeatures:
        """Extract all feature types from a single audio array."""
        return AudioFeatures(
            mel_spectrogram=self.extract_mel_spectrogram(audio),
            log_mel_spectrogram=self.extract_log_mel_spectrogram(audio),
            mfccs=self.extract_mfccs(audio),
            label=label,
            filename=filename,
        )

    def extract_batch(
        self, audios: list, labels: list, filenames: list = None
    ) -> list:
        """Extract features from a batch of audio arrays."""
        if filenames is None:
            filenames = [f"sample_{i}" for i in range(len(audios))]

        features = []
        for audio, label, fname in zip(audios, labels, filenames):
            features.append(self.extract_all(audio, label, fname))
        return features


class Wav2VecFeatureExtractor:
    """
    Extract deep embeddings from Wav2Vec2 / HuBERT.
    Uses the model's internal representations as features.
    """

    def __init__(
        self,
        model_name: str = "facebook/wav2vec2-base",
        device: str = None,
        pooling: str = "mean",  # "mean", "cls", "last"
    ):
        self.model_name = model_name
        self.pooling = pooling
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        from transformers import Wav2Vec2Model, Wav2Vec2Processor

        print(f"Loading {model_name}...")
        self.processor = Wav2Vec2Processor.from_pretrained(model_name)
        self.model = Wav2Vec2Model.from_pretrained(model_name).to(self.device)
        self.model.eval()
        print(f"  Model loaded on {self.device}")

    @torch.no_grad()
    def extract(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Extract Wav2Vec2 embeddings from a single audio array.
        Returns a 1D embedding vector.
        """
        # Ensure correct sample rate
        if sr != 16000:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000

        inputs = self.processor(
            audio,
            sampling_rate=sr,
            return_tensors="pt",
            padding=True,
        )
        input_values = inputs.input_values.to(self.device)
        outputs = self.model(input_values, output_hidden_states=True)

        # Use last hidden state
        hidden_states = outputs.last_hidden_state  # (batch, time, features)

        if self.pooling == "mean":
            embedding = hidden_states.mean(dim=1).squeeze().cpu().numpy()
        elif self.pooling == "cls":
            embedding = hidden_states[:, 0, :].squeeze().cpu().numpy()
        elif self.pooling == "last":
            embedding = hidden_states[:, -1, :].squeeze().cpu().numpy()
        else:
            raise ValueError(f"Unknown pooling: {self.pooling}")

        return embedding

    @torch.no_grad()
    def extract_sequence(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Extract the full sequence of Wav2Vec2 embeddings.
        Returns shape (time_steps, 768) for base model.
        """
        if sr != 16000:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
            sr = 16000

        inputs = self.processor(
            audio,
            sampling_rate=sr,
            return_tensors="pt",
            padding=True,
        )
        input_values = inputs.input_values.to(self.device)
        outputs = self.model(input_values)
        return outputs.last_hidden_state.squeeze().cpu().numpy()

    def extract_batch(self, audios: list, sr: int = 16000) -> np.ndarray:
        """Extract embeddings from a batch of audio arrays. Returns (N, dim)."""
        embeddings = [self.extract(audio, sr) for audio in audios]
        return np.array(embeddings)


class FeaturePipeline:
    """
    Unified feature pipeline that handles preprocessing + extraction.
    """

    def __init__(self, sr: int = 16000, segment_duration: float = 5.0):
        self.sr = sr
        self.segment_duration = segment_duration
        self.feature_extractor = FeatureExtractor(
            sr=sr, target_length=int(segment_duration * sr / 512) + 1
        )
        self.wav2vec_extractor: Optional[Wav2VecFeatureExtractor] = None

    def enable_wav2vec(self, model_name: str = "facebook/wav2vec2-base"):
        """Enable Wav2Vec2 embedding extraction."""
        self.wav2vec_extractor = Wav2VecFeatureExtractor(model_name=model_name)

    def process_segments(self, segments) -> Dict:
        """
        Process a list of AudioSegment objects into feature arrays.
        Returns dict with keys: mfccs, mel_specs, log_mel_specs, labels, (optional) wav2vec_embeds.
        """
        mfccs = []
        mel_specs = []
        log_mel_specs = []
        labels = []
        wav2vec_embeds = []

        for seg in segments:
            audio = seg.audio.astype(np.float32)
            label_int = 1 if seg.label == "fake" else 0

            feats = self.feature_extractor.extract_all(audio, label_int, seg.source_file)
            mfccs.append(feats.mfccs)
            mel_specs.append(feats.mel_spectrogram)
            log_mel_specs.append(feats.log_mel_spectrogram)
            labels.append(label_int)

            if self.wav2vec_extractor is not None:
                embed = self.wav2vec_extractor.extract(audio, self.sr)
                wav2vec_embeds.append(embed)

        result = {
            "mfccs": np.array(mfccs),
            "mel_specs": np.array(mel_specs),
            "log_mel_specs": np.array(log_mel_specs),
            "labels": np.array(labels),
        }

        if wav2vec_embeds:
            result["wav2vec_embeds"] = np.array(wav2vec_embeds)

        return result

    def visualize_mel_spectrogram(
        self, audio: np.ndarray, save_path: Optional[str] = None
    ) -> np.ndarray:
        """Generate a mel-spectrogram visualization array (for UI rendering)."""
        mel = self.feature_extractor.extract_log_mel_spectrogram(audio)
        return mel

    def visualize_waveform(self, audio: np.ndarray) -> np.ndarray:
        """Return time-domain waveform for visualization."""
        times = np.arange(len(audio)) / self.sr
        return np.column_stack([times, audio])

"""
Audio preprocessing pipeline for the Deepfake Detector.
Handles VAD, resampling, segmentation, and normalization.
"""

import os
import numpy as np
import librosa
import soundfile as sf
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass
import warnings

warnings.filterwarnings("ignore")


@dataclass
class AudioSegment:
    """Represents a processed audio segment."""
    audio: np.ndarray
    sr: int
    label: str  # "real" or "fake"
    source_file: str
    start_sample: int
    duration: float


class VoiceActivityDetector:
    """
    Simple energy-based VAD with optional webrtcvad.
    Trims silence from audio clips.
    """

    def __init__(self, frame_duration_ms: int = 30, threshold_db: float = -40.0):
        self.frame_duration_ms = frame_duration_ms
        self.threshold_db = threshold_db
        self._webrtcvad_available = False
        try:
            import webrtcvad
            self._webrtcvad_available = True
            self._vad = webrtcvad.Vad(2)  # aggressiveness 0-3
        except ImportError:
            self._vad = None

    def detect_vad_webrtcvad(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Use WebRTC VAD for voice activity detection."""
        import webrtcvad

        # Convert to int16 for webrtcvad
        audio_int16 = (audio * 32767).astype(np.int16)

        frame_size = int(sr * self.frame_duration_ms / 1000)
        frames = []
        voiced_frames = []

        for i in range(0, len(audio_int16) - frame_size, frame_size):
            frame = audio_int16[i: i + frame_size]
            is_voiced = self._vad.is_speech(frame.tobytes(), sr)
            frames.append((frame, is_voiced))
            voiced_frames.append(is_voiced)

        if not voiced_frames:
            return audio

        # Find first and last voiced frame
        first_voiced = next((i for i, v in enumerate(voiced_frames) if v), None)
        last_voiced = next(
            (i for i in range(len(voiced_frames) - 1, -1, -1) if voiced_frames[i]),
            None,
        )

        if first_voiced is None or last_voiced is None:
            return audio

        start = first_voiced * frame_size
        end = min((last_voiced + 1) * frame_size, len(audio))
        return audio[start:end]

    def detect_vad_energy(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Simple energy-based VAD fallback."""
        hop_length = int(sr * self.frame_duration_ms / 1000)
        rms = librosa.feature.rms(y=audio, hop_length=hop_length)[0]
        threshold = 10 ** (self.threshold_db / 20)

        voiced_mask = rms > threshold
        if not np.any(voiced_mask):
            return audio

        voiced_indices = np.where(voiced_mask)[0]
        start = int(voiced_indices[0] * hop_length)
        end = min(int((voiced_indices[-1] + 1) * hop_length), len(audio))
        return audio[start:end]

    def trim_silence(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """Remove silence from beginning and end using the best available method."""
        if self._webrtcvad_available:
            try:
                return self.detect_vad_webrtcvad(audio, sr)
            except Exception:
                pass
        return self.detect_vad_energy(audio, sr)


class AudioPreprocessor:
    """
    Full preprocessing pipeline: resample -> VAD -> segment -> normalize.
    """

    def __init__(
        self,
        target_sr: int = 16000,
        segment_duration: float = 5.0,
        vad_threshold_db: float = -40.0,
    ):
        self.target_sr = target_sr
        self.segment_duration = segment_duration
        self.vad = VoiceActivityDetector(threshold_db=vad_threshold_db)

    def load_audio(self, filepath: str) -> Tuple[np.ndarray, int]:
        """Load and resample audio to target sample rate."""
        audio, sr = librosa.load(filepath, sr=self.target_sr, mono=True)
        return audio, sr

    def resample(self, audio: np.ndarray, orig_sr: int, target_sr: int = None) -> np.ndarray:
        """Resample audio to target sample rate."""
        if target_sr is None:
            target_sr = self.target_sr
        if orig_sr != target_sr:
            audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)
        return audio

    def normalize(self, audio: np.ndarray) -> np.ndarray:
        """Peak normalize audio to [-1, 1]."""
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak
        return audio

    def segment_audio(
        self, audio: np.ndarray, sr: int, label: str, source_file: str
    ) -> List[AudioSegment]:
        """Split audio into fixed-duration segments."""
        segment_samples = int(self.segment_duration * sr)
        segments = []
        total_samples = len(audio)

        if total_samples < segment_samples:
            # Pad short clips
            padded = np.zeros(segment_samples)
            padded[:total_samples] = audio
            segments.append(
                AudioSegment(
                    audio=padded,
                    sr=sr,
                    label=label,
                    source_file=source_file,
                    start_sample=0,
                    duration=self.segment_duration,
                )
            )
        else:
            start = 0
            while start + segment_samples <= total_samples:
                chunk = audio[start: start + segment_samples]
                segments.append(
                    AudioSegment(
                        audio=chunk,
                        sr=sr,
                        label=label,
                        source_file=source_file,
                        start_sample=start,
                        duration=self.segment_duration,
                    )
                )
                start += segment_samples

        return segments

    def process_file(
        self, filepath: str, label: str
    ) -> List[AudioSegment]:
        """Full pipeline for a single file: load -> resample -> VAD -> normalize -> segment."""
        audio, sr = self.load_audio(filepath)
        audio = self.vad.trim_silence(audio, sr)
        audio = self.normalize(audio)
        segments = self.segment_audio(audio, sr, label, filepath)
        return segments

    def process_directory(
        self, real_dir: str, fake_dir: str
    ) -> List[AudioSegment]:
        """Process all audio files in real and fake directories."""
        all_segments = []

        for label, audio_dir in [("real", real_dir), ("fake", fake_dir)]:
            if not os.path.exists(audio_dir):
                print(f"Warning: Directory not found: {audio_dir}")
                continue

            audio_extensions = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}
            files = [
                f
                for f in Path(audio_dir).rglob("*")
                if f.suffix.lower() in audio_extensions
            ]

            print(f"Processing {len(files)} {label} audio files...")
            for filepath in files:
                try:
                    segments = self.process_file(str(filepath), label)
                    all_segments.extend(segments)
                except Exception as e:
                    print(f"  Error processing {filepath}: {e}")

        return all_segments

    def save_segments(
        self,
        segments: List[AudioSegment],
        output_dir: str,
        format: str = "wav",
    ):
        """Save processed segments to disk."""
        os.makedirs(output_dir, exist_ok=True)

        for i, seg in enumerate(segments):
            filename = f"{seg.label}_{i:06d}.{format}"
            filepath = os.path.join(output_dir, filename)
            sf.write(filepath, seg.audio, seg.sr)

        print(f"Saved {len(segments)} segments to {output_dir}")


def train_val_test_split(
    segments: List[AudioSegment],
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
) -> Tuple[List[AudioSegment], List[AudioSegment], List[AudioSegment]]:
    """
    Split segments with ZERO speaker overlap between train and test.
    Groups by source_file and assigns entire source files to splits.
    """
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6

    rng = np.random.RandomState(seed)
    source_files = list(set(seg.source_file for seg in segments))
    rng.shuffle(source_files)

    n_train = int(len(source_files) * train_ratio)
    n_val = int(len(source_files) * val_ratio)

    train_sources = set(source_files[:n_train])
    val_sources = set(source_files[n_train: n_train + n_val])
    test_sources = set(source_files[n_train + n_val:])

    train = [s for s in segments if s.source_file in train_sources]
    val = [s for s in segments if s.source_file in val_sources]
    test = [s for s in segments if s.source_file in test_sources]

    print(
        f"Split: {len(train)} train, {len(val)} val, {len(test)} test "
        f"(from {len(train_sources)} + {len(val_sources)} + {len(test_sources)} source files)"
    )

    return train, val, test

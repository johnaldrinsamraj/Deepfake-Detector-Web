"""
Synthetic audio generation for creating deepfake training data.
Supports multiple TTS backends: Bark, Coqui TTS, and OpenAI Whisper-based approaches.
"""

import os
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import List, Optional


class SyntheticAudioGenerator:
    """
    Generate synthetic audio for training deepfake detection models.
    """

    def __init__(self, output_dir: str = "data/fake", target_sr: int = 16000):
        self.output_dir = output_dir
        self.target_sr = target_sr
        os.makedirs(output_dir, exist_ok=True)

    def generate_with_bark(
        self,
        text: str,
        speaker_name: str = "v2/en_speaker_0",
        output_name: str = "bark_output",
    ) -> str:
        """
        Generate audio using Bark TTS.
        pip install git+https://github.com/suno-ai/bark.git
        """
        try:
            from bark import SAMPLE_RATE, generate_audio, preload_models

            preload_models()
            audio_array = generate_audio(text, history_prompt=speaker_name)

            output_path = os.path.join(self.output_dir, f"{output_name}.wav")
            sf.write(output_path, audio_array, SAMPLE_RATE)
            print(f"  Generated: {output_path}")
            return output_path

        except ImportError:
            print("  Bark not installed. Install with: pip install git+https://github.com/suno-ai/bark.git")
            return ""

    def generate_with_coqui(
        self,
        text: str,
        model_name: str = "tts_models/en/ljspeech/tacotron2-DDC",
        output_name: str = "coqui_output",
    ) -> str:
        """
        Generate audio using Coqui TTS.
        pip install TTS
        """
        try:
            from TTS.api import TTS

            tts = TTS(model_name=model_name)
            output_path = os.path.join(self.output_dir, f"{output_name}.wav")
            tts.tts_to_file(text=text, file_path=output_path)
            print(f"  Generated: {output_path}")
            return output_path

        except ImportError:
            print("  Coqui TTS not installed. Install with: pip install TTS")
            return ""

    def generate_with_edge_tts(
        self,
        text: str,
        voice: str = "en-US-GuyNeural",
        output_name: str = "edge_output",
    ) -> str:
        """
        Generate audio using edge-tts (free, no GPU needed).
        pip install edge-tts
        """
        try:
            import edge_tts
            import asyncio

            output_path = os.path.join(self.output_dir, f"{output_name}.wav")

            async def _generate():
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_path)

            asyncio.run(_generate())
            print(f"  Generated: {output_path}")
            return output_path

        except ImportError:
            print("  edge-tts not installed. Install with: pip install edge-tts")
            return ""

    def generate_with_piper(
        self,
        text: str,
        model_path: str = "",
        output_name: str = "piper_output",
    ) -> str:
        """
        Generate audio using Piper TTS (fast, local).
        Requires piper binary: https://github.com/rhasspy/piper
        """
        import subprocess
        import tempfile

        if not model_path:
            print("  Piper requires a model path. Download from: https://github.com/rhasspy/piper")
            return ""

        output_path = os.path.join(self.output_dir, f"{output_name}.wav")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            tmp_path = f.name

        try:
            cmd = f"cat {tmp_path} | piper --model {model_path} --output_file {output_path}"
            subprocess.run(cmd, shell=True, check=True)
            print(f"  Generated: {output_path}")
            return output_path
        except Exception as e:
            print(f"  Piper error: {e}")
            return ""
        finally:
            os.unlink(tmp_path)

    def generate_synthetic_dataset(
        self,
        real_audio_dir: str,
        scripts: List[str],
        backend: str = "edge_tts",
        voice: str = "en-US-GuyNeural",
    ) -> List[str]:
        """
        Generate a batch of synthetic audio clips using provided scripts.
        """
        print(f"\nGenerating synthetic audio with {backend}...")
        generated = []

        for i, text in enumerate(scripts):
            output_name = f"synthetic_{i:04d}"

            if backend == "bark":
                path = self.generate_with_bark(text, output_name=output_name)
            elif backend == "coqui":
                path = self.generate_with_coqui(text, output_name=output_name)
            elif backend == "edge_tts":
                path = self.generate_with_edge_tts(
                    text, voice=voice, output_name=output_name
                )
            elif backend == "piper":
                path = self.generate_with_piper(text, output_name=output_name)
            else:
                raise ValueError(f"Unknown backend: {backend}")

            if path:
                generated.append(path)

        print(f"Generated {len(generated)} synthetic clips")
        return generated


# ============================================================
# Sample government announcement scripts for deepfake generation
# ============================================================

SAMPLE_GOVERNMENT_SCRIPTS = [
    "Attention all citizens. This is an emergency broadcast. Due to severe weather conditions, all residents in coastal areas must evacuate immediately.",
    "Good evening. I am here to address the nation regarding the recent developments in our foreign policy negotiations.",
    "This is an official announcement from the department of homeland security. Please remain calm and follow the instructions of local authorities.",
    "Fellow citizens, the results of the recent election have been certified. I want to assure you that our democratic institutions remain strong.",
    "Due to a critical infrastructure failure, power will be restored to affected areas within the next forty-eight hours.",
    "The president will address the nation at eight PM eastern time regarding the ongoing economic recovery efforts.",
    "This is a test of the emergency alert system. This is only a test. No action is required at this time.",
    "New regulations regarding international trade will take effect starting next Monday. Businesses should review the updated compliance requirements.",
]

if __name__ == "__main__":
    # Example usage
    generator = SyntheticAudioGenerator(output_dir="data/fake")

    print("Available TTS backends:")
    print("  1. edge-tts (free, no GPU)")
    print("  2. bark (open source, GPU recommended)")
    print("  3. coqui TTS (open source)")
    print("  4. piper (fast, local)")

    # Try edge-tts first (most accessible)
    generated = generator.generate_synthetic_dataset(
        real_audio_dir="data/real",
        scripts=SAMPLE_GOVERNMENT_SCRIPTS[:3],
        backend="edge_tts",
    )
    print(f"\nGenerated files: {generated}")

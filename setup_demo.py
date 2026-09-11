#!/usr/bin/env python3
"""
Demo Reel Setup
Curates 8-10 distinct audio samples for jury/audience presentation.
Generates sample clips if none exist.
"""

import os
import numpy as np
import soundfile as sf
from pathlib import Path

DEMO_DIR = "demo_clips"


def generate_demo_clips():
    """Generate synthetic demo clips for the presentation."""
    os.makedirs(DEMO_DIR, exist_ok=True)

    sr = 16000

    print("🎬 Generating Demo Reel Clips")
    print("=" * 50)

    # Try to generate real-sounding clips using edge-tts
    try:
        import edge_tts
        import asyncio

        real_scripts = [
            ("real_01_presidential", "My fellow Americans, tonight I address you from the Oval Office regarding matters of national security."),
            ("real_02_press_briefing", "Good afternoon. The secretary will now take your questions regarding today's announcement."),
            ("real_03_emergency_alert", "This is the national emergency broadcast system. This is not a test."),
            ("real_04_policy_statement", "The new economic policy will take effect immediately, benefiting working families across the nation."),
        ]

        fake_scripts = [
            ("fake_01_clone_speech", "I am announcing my immediate resignation effective at midnight tonight. God bless America."),
            ("fake_02_fake_emergency", "Attention all citizens. The military has been deployed to major cities. Stay indoors immediately."),
            ("fake_03_fake_policy", "Effective immediately, all citizens must report to their nearest government office for mandatory verification."),
            ("fake_04_fake_statement", "I can confirm that the classified documents have been transferred to the foreign embassy."),
        ]

        all_scripts = real_scripts + fake_scripts

        async def generate_clip(name, text):
            output_path = os.path.join(DEMO_DIR, f"{name}.wav")
            if os.path.exists(output_path):
                print(f"  ⏭️  {name}.wav already exists, skipping")
                return output_path

            communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
            tmp_path = os.path.join(DEMO_DIR, f"{name}.mp3")
            await communicate.save(tmp_path)

            # Convert to wav
            import subprocess
            subprocess.run([
                "ffmpeg", "-i", tmp_path, "-ar", str(sr), "-ac", "1",
                output_path, "-y"
            ], capture_output=True)

            # Clean up mp3
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            print(f"  ✅ Generated: {name}.wav")
            return output_path

        async def generate_all():
            tasks = [generate_clip(name, text) for name, text in all_scripts]
            return await asyncio.gather(*tasks)

        clips = asyncio.run(generate_all())
        print(f"\nGenerated {len(clips)} demo clips")

    except ImportError:
        print("edge-tts not installed. Generating synthetic placeholder clips...")
        generate_placeholder_clips(sr)
    except Exception as e:
        print(f"Error generating with edge-tts: {e}")
        print("Generating synthetic placeholder clips...")
        generate_placeholder_clips(sr)

    print(f"\n📂 Demo clips saved to: {DEMO_DIR}/")
    print("\nPresentation flow:")
    print("  1. Launch: streamlit run app.py")
    print("  2. Go to 'Demo Reel' tab")
    print("  3. Select clip -> Play for jury -> Gather votes -> Run detector")
    print("  4. Reveal verdict with spectral evidence")


def generate_placeholder_clips(sr=16000):
    """Generate placeholder clips with different spectral characteristics."""
    clips = []

    clip_configs = [
        ("real_01_speech.wav", "real", 0.15),
        ("real_02_presser.wav", "real", 0.12),
        ("real_03_broadcast.wav", "real", 0.18),
        ("real_04_address.wav", "real", 0.14),
        ("fake_01_clone.wav", "fake", 0.25),
        ("fake_02_emergency.wav", "fake", 0.30),
        ("fake_03_statement.wav", "fake", 0.22),
        ("fake_04_announcement.wav", "fake", 0.28),
    ]

    for name, label, noise_level in clip_configs:
        filepath = os.path.join(DEMO_DIR, name)
        if os.path.exists(filepath):
            print(f"  ⏭️  {name} already exists, skipping")
            continue

        # Generate synthetic audio with different characteristics
        duration = 5.0  # seconds
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)

        if label == "real":
            # Simulate natural speech: multiple harmonics, less noise
            audio = (
                0.3 * np.sin(2 * np.pi * 200 * t) +
                0.2 * np.sin(2 * np.pi * 400 * t) +
                0.15 * np.sin(2 * np.pi * 600 * t) +
                0.1 * np.sin(2 * np.pi * 1200 * t) +
                noise_level * np.random.randn(len(t))
            )
            # Add natural amplitude modulation (speech-like)
            mod = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
            audio *= mod
        else:
            # Simulate synthetic: more high-frequency content, different harmonics
            audio = (
                0.3 * np.sin(2 * np.pi * 250 * t) +
                0.2 * np.sin(2 * np.pi * 500 * t) +
                0.15 * np.sin(2 * np.pi * 1000 * t) +
                0.2 * np.sin(2 * np.pi * 3000 * t) +
                0.15 * np.sin(2 * np.pi * 6000 * t) +
                noise_level * np.random.randn(len(t))
            )

        audio = audio.astype(np.float32)
        audio = audio / np.max(np.abs(audio)) * 0.9  # Normalize

        sf.write(filepath, audio, sr)
        print(f"  ✅ Generated placeholder: {name}")
        clips.append(filepath)

    return clips


if __name__ == "__main__":
    generate_demo_clips()

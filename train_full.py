#!/usr/bin/env python3
"""
Full training pipeline for the Audio Deepfake Detector.
Usage:
    python train_full.py --model_type cnn --epochs 30
    python train_full.py --model_type wav2vec --epochs 20
    python train_full.py --model_type resnet --epochs 30
"""

import os
import sys
import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader

from preprocessing import AudioPreprocessor, train_val_test_split
from features import FeatureExtractor, FeaturePipeline, Wav2VecFeatureExtractor
from models import create_model, TemperatureScaler
from train import AudioFeatureDataset, Wav2VecDataset, Trainer, print_evaluation_report


def parse_args():
    parser = argparse.ArgumentParser(description="Train Audio Deepfake Detector")
    parser.add_argument("--real_dir", type=str, default="data/real", help="Directory with real audio")
    parser.add_argument("--fake_dir", type=str, default="data/fake", help="Directory with fake audio")
    parser.add_argument("--model_type", type=str, default="cnn", choices=["cnn", "resnet", "wav2vec"])
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--segment_duration", type=float, default=5.0)
    parser.add_argument("--save_dir", type=str, default="checkpoints")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    print("=" * 60)
    print("AUDIO DEEPFAKE DETECTOR - TRAINING PIPELINE")
    print("=" * 60)
    print(f"Model: {args.model_type}")
    print(f"Real audio: {args.real_dir}")
    print(f"Fake audio: {args.fake_dir}")
    print(f"Segment duration: {args.segment_duration}s")
    print(f"Epochs: {args.epochs}")
    print(f"Batch size: {args.batch_size}")
    print(f"Learning rate: {args.lr}")
    print()

    # ============================================================
    # Phase 1: Preprocessing
    # ============================================================
    print("=" * 60)
    print("PHASE 1: PREPROCESSING")
    print("=" * 60)

    preprocessor = AudioPreprocessor(
        target_sr=16000,
        segment_duration=args.segment_duration,
    )

    # Check if directories exist
    if not os.path.exists(args.real_dir):
        print(f"\n⚠️  Real audio directory not found: {args.real_dir}")
        print("Creating sample directory structure...")
        os.makedirs(args.real_dir, exist_ok=True)
        os.makedirs(args.fake_dir, exist_ok=True)

        print("\n📝 Please add audio files to:")
        print(f"   Real: {args.real_dir}/")
        print(f"   Fake: {args.fake_dir}/")
        print("\nSupported formats: .wav, .flac, .mp3, .m4a, .ogg, .opus")
        print("\nTo generate synthetic training data, run:")
        print("   python generate_synthetic.py")

        # Create synthetic data if none exists
        print("\nGenerating synthetic training data with edge-tts...")
        try:
            from generate_synthetic import SyntheticAudioGenerator, SAMPLE_GOVERNMENT_SCRIPTS

            generator = SyntheticAudioGenerator(
                output_dir=args.fake_dir,
                target_sr=16000,
            )
            generator.generate_synthetic_dataset(
                real_audio_dir=args.real_dir,
                scripts=SAMPLE_GOVERNMENT_SCRIPTS,
                backend="edge_tts",
            )
            print("✅ Synthetic data generated!")
        except Exception as e:
            print(f"Could not generate synthetic data: {e}")
            print("Please add audio files manually.")
            return

    # Process all audio
    print("\nProcessing audio files...")
    segments = preprocessor.process_directory(args.real_dir, args.fake_dir)

    if not segments:
        print("\n❌ No audio segments found. Please add audio files.")
        return

    print(f"\nTotal segments: {len(segments)}")

    # Split data
    train_segs, val_segs, test_segs = train_val_test_split(
        segments, seed=args.seed
    )

    # ============================================================
    # Phase 2: Feature Extraction
    # ============================================================
    print("\n" + "=" * 60)
    print("PHASE 2: FEATURE EXTRACTION")
    print("=" * 60)

    feature_pipeline = FeaturePipeline(
        sr=16000,
        segment_duration=args.segment_duration,
    )

    if args.model_type == "wav2vec":
        print("Extracting Wav2Vec2 embeddings (this may take a while)...")
        feature_pipeline.enable_wav2vec("facebook/wav2vec2-base")

    print("Extracting features from train set...")
    train_features = feature_pipeline.process_segments(train_segs)

    print("Extracting features from val set...")
    val_features = feature_pipeline.process_segments(val_segs)

    print("Extracting features from test set...")
    test_features = feature_pipeline.process_segments(test_segs)

    print(f"\nFeature shapes:")
    print(f"  MFCCs: {train_features['mfccs'].shape}")
    print(f"  Mel-specs: {train_features['mel_specs'].shape}")
    print(f"  Log-mel-specs: {train_features['log_mel_specs'].shape}")
    if "wav2vec_embeds" in train_features:
        print(f"  Wav2Vec embeddings: {train_features['wav2vec_embeds'].shape}")

    # ============================================================
    # Phase 3: Model Training
    # ============================================================
    print("\n" + "=" * 60)
    print("PHASE 3: MODEL TRAINING")
    print("=" * 60)

    # Choose feature type and create datasets
    if args.model_type == "wav2vec":
        train_dataset = Wav2VecDataset(train_segs)
        val_dataset = Wav2VecDataset(val_segs)
        test_dataset = Wav2VecDataset(test_segs)
    else:
        train_dataset = AudioFeatureDataset(train_features, "log_mel_specs")
        val_dataset = AudioFeatureDataset(val_features, "log_mel_specs")
        test_dataset = AudioFeatureDataset(test_features, "log_mel_specs")

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0
    )
    test_loader = DataLoader(
        test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0
    )

    # Create model
    model_kwargs = {}
    if args.model_type == "wav2vec":
        model_kwargs["freeze_layers"] = 6
        model_kwargs["dropout"] = 0.3

    model = create_model(args.model_type, num_classes=2, **model_kwargs)

    n_params = sum(p.numel() for p in model.parameters())
    n_trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\nModel: {args.model_type}")
    print(f"  Total parameters: {n_params:,}")
    print(f"  Trainable parameters: {n_trainable:,}")

    # Train
    trainer = Trainer(
        model=model,
        learning_rate=args.lr,
    )

    history = trainer.fit(
        train_loader=train_loader,
        val_loader=val_loader,
        epochs=args.epochs,
        save_dir=args.save_dir,
    )

    # ============================================================
    # Phase 4: Final Evaluation
    # ============================================================
    print("\n" + "=" * 60)
    print("PHASE 4: FINAL EVALUATION ON TEST SET")
    print("=" * 60)

    test_metrics = trainer.evaluate(test_loader)
    print_evaluation_report(test_metrics, test_loader)

    # Save test metrics
    import json
    test_metrics_path = os.path.join(args.save_dir, "test_metrics.json")
    with open(test_metrics_path, "w") as f:
        json.dump(test_metrics, f, indent=2)
    print(f"\nTest metrics saved to: {test_metrics_path}")

    print("\n" + "=" * 60)
    print("✅ TRAINING COMPLETE")
    print(f"   Model saved to: {args.save_dir}/best_model.pt")
    print(f"   Calibration saved to: {args.save_dir}/calibration.pt")
    print(f"   Launch dashboard: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

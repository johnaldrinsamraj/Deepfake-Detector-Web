"""
Training pipeline for deepfake detection models.
Includes training loops, evaluation metrics, calibration, and checkpointing.
"""

import os
import json
import time
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from typing import Dict, Optional, Tuple
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
    confusion_matrix,
    classification_report,
)

from models import TemperatureScaler


# ============================================================
# Dataset
# ============================================================


class AudioFeatureDataset(Dataset):
    """PyTorch dataset for pre-extracted audio features."""

    def __init__(self, features: dict, feature_type: str = "log_mel_specs"):
        """
        Args:
            features: dict from FeaturePipeline.process_segments()
            feature_type: which feature to use ("log_mel_specs", "mel_specs", "mfccs", "wav2vec_embeds")
        """
        self.feature_type = feature_type
        self.data = features[feature_type].astype(np.float32)
        self.labels = features["labels"].astype(np.int64)

        # Add channel dimension for CNN models (N, H, W) -> (N, 1, H, W)
        if self.data.ndim == 3:
            self.data = self.data[:, np.newaxis, :, :]

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        x = torch.from_numpy(self.data[idx])
        y = torch.tensor(self.labels[idx], dtype=torch.long)
        return x, y


class Wav2VecDataset(Dataset):
    """Dataset for raw waveform input to Wav2Vec models."""

    def __init__(self, segments):
        self.segments = segments

    def __len__(self):
        return len(self.segments)

    def __getitem__(self, idx):
        seg = self.segments[idx]
        audio = seg.audio.astype(np.float32)
        label = 1 if seg.label == "fake" else 0
        return torch.from_numpy(audio), torch.tensor(label, dtype=torch.long)


# ============================================================
# Training
# ============================================================


class Trainer:
    """Handles model training, validation, and evaluation."""

    def __init__(
        self,
        model: nn.Module,
        device: str = None,
        learning_rate: float = 1e-4,
        weight_decay: float = 1e-4,
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = model.to(self.device)
        self.criterion = nn.CrossEntropyLoss()
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.scaler = TemperatureScaler()

    def train_epoch(
        self, dataloader: DataLoader, optimizer: optim.Optimizer
    ) -> Dict[str, float]:
        """Train for one epoch."""
        self.model.train()
        total_loss = 0.0
        all_preds = []
        all_labels = []

        for batch_x, batch_y in dataloader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            optimizer.zero_grad()
            logits = self.model(batch_x)
            loss = self.criterion(logits, batch_y)
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            optimizer.step()

            total_loss += loss.item() * batch_x.size(0)
            preds = torch.argmax(logits, dim=1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(batch_y.cpu().numpy())

        n = len(dataloader.dataset)
        return {
            "loss": total_loss / n,
            "accuracy": accuracy_score(all_labels, all_preds),
        }

    @torch.no_grad()
    def evaluate(self, dataloader: DataLoader) -> Dict:
        """Evaluate on a dataset split."""
        self.model.eval()
        total_loss = 0.0
        all_preds = []
        all_labels = []
        all_probs = []

        for batch_x, batch_y in dataloader:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            logits = self.model(batch_x)
            loss = self.criterion(logits, batch_y)

            total_loss += loss.item() * batch_x.size(0)
            probs = torch.softmax(logits, dim=1)
            preds = torch.argmax(probs, dim=1)

            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(batch_y.cpu().numpy())
            all_probs.extend(probs[:, 1].detach().cpu().numpy())

        n = len(dataloader.dataset)
        all_preds = np.array(all_preds)
        all_labels = np.array(all_labels)
        all_probs = np.array(all_probs)

        metrics = {
            "loss": total_loss / n,
            "accuracy": accuracy_score(all_labels, all_preds),
            "precision": precision_score(all_labels, all_preds, zero_division=0),
            "recall": recall_score(all_labels, all_preds, zero_division=0),
            "confusion_matrix": confusion_matrix(all_labels, all_preds).tolist(),
        }

        try:
            metrics["roc_auc"] = roc_auc_score(all_labels, all_probs)
        except ValueError:
            metrics["roc_auc"] = 0.0

        return metrics

    def calibrate(
        self, val_loader: DataLoader
    ) -> float:
        """Calibrate probability outputs using temperature scaling."""
        self.model.eval()
        all_logits = []
        all_labels = []

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(self.device)
                logits = self.model(batch_x)
                all_logits.append(logits.cpu())
                all_labels.append(batch_y)

        logits_tensor = torch.cat(all_logits, dim=0)
        labels_tensor = torch.cat(all_labels, dim=0)

        self.scaler.calibrate(logits_tensor, labels_tensor)
        return self.scaler.temperature.item()

    def fit(
        self,
        train_loader: DataLoader,
        val_loader: DataLoader,
        epochs: int = 30,
        patience: int = 7,
        save_dir: str = "checkpoints",
    ) -> Dict:
        """Full training loop with early stopping."""
        os.makedirs(save_dir, exist_ok=True)

        optimizer = optim.AdamW(
            self.model.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay,
        )
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=3
        )

        best_val_loss = float("inf")
        patience_counter = 0
        history = {"train": [], "val": []}

        print(f"\nTraining on {self.device} for up to {epochs} epochs")
        print("-" * 60)

        for epoch in range(1, epochs + 1):
            t0 = time.time()

            train_metrics = self.train_epoch(train_loader, optimizer)
            val_metrics = self.evaluate(val_loader)
            scheduler.step(val_metrics["loss"])

            elapsed = time.time() - t0
            history["train"].append(train_metrics)
            history["val"].append(val_metrics)

            print(
                f"Epoch {epoch:3d}/{epochs} | "
                f"Train Loss: {train_metrics['loss']:.4f} Acc: {train_metrics['accuracy']:.4f} | "
                f"Val Loss: {val_metrics['loss']:.4f} Acc: {val_metrics['accuracy']:.4f} "
                f"ROC-AUC: {val_metrics['roc_auc']:.4f} | {elapsed:.1f}s"
            )

            # Early stopping
            if val_metrics["loss"] < best_val_loss:
                best_val_loss = val_metrics["loss"]
                patience_counter = 0
                self.save_checkpoint(os.path.join(save_dir, "best_model.pt"))
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    print(f"\nEarly stopping at epoch {epoch}")
                    break

        # Load best model and calibrate
        self.load_checkpoint(os.path.join(save_dir, "best_model.pt"))
        temperature = self.calibrate(val_loader)

        # Save calibration
        torch.save({"temperature": temperature}, os.path.join(save_dir, "calibration.pt"))

        # Final evaluation
        final_metrics = self.evaluate(val_loader)
        final_metrics["calibration_temperature"] = temperature
        history["final_val"] = final_metrics

        # Save history
        with open(os.path.join(save_dir, "history.json"), "w") as f:
            json.dump(history, f, indent=2)

        print("\n" + "=" * 60)
        print("Training Complete")
        print(f"Best Val Loss: {best_val_loss:.4f}")
        print(f"Calibration Temperature: {temperature:.3f}")
        print(f"Final Val Accuracy: {final_metrics['accuracy']:.4f}")
        print(f"Final Val ROC-AUC: {final_metrics['roc_auc']:.4f}")
        print(f"Confusion Matrix: {final_metrics['confusion_matrix']}")
        print("=" * 60)

        return history

    def save_checkpoint(self, path: str):
        """Save model weights."""
        torch.save(self.model.state_dict(), path)

    def load_checkpoint(self, path: str):
        """Load model weights."""
        state_dict = torch.load(path, map_location=self.device)
        self.model.load_state_dict(state_dict)


def print_evaluation_report(test_metrics: Dict, test_loader: DataLoader = None):
    """Print a detailed evaluation report."""
    print("\n" + "=" * 60)
    print("FINAL EVALUATION REPORT")
    print("=" * 60)
    print(f"  Accuracy:     {test_metrics['accuracy']:.4f}")
    print(f"  Precision:    {test_metrics['precision']:.4f}")
    print(f"  Recall:       {test_metrics['recall']:.4f}")
    print(f"  ROC-AUC:      {test_metrics['roc_auc']:.4f}")
    print(f"  Confusion Matrix:")
    cm = test_metrics["confusion_matrix"]
    print(f"                  Predicted")
    print(f"                  Real    Fake")
    print(f"    Actual Real  [{cm[0][0]:5d}  {cm[0][1]:5d}]")
    print(f"    Actual Fake  [{cm[1][0]:5d}  {cm[1][1]:5d}]")
    if "calibration_temperature" in test_metrics:
        print(f"  Calibration T: {test_metrics['calibration_temperature']:.3f}")
    print("=" * 60)

"""
Deepfake detection models.
Option A: 2D CNN on Mel-Spectrograms.
Option B: Wav2Vec2 with classification head.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


# ============================================================
# Option A: 2D CNN on Mel-Spectrograms
# ============================================================


class DeepfakeCNN(nn.Module):
    """
    Lightweight 2D CNN that takes log-Mel-spectrograms as input.
    Input shape: (batch, 1, n_mels, time_steps)
    """

    def __init__(self, n_mels: int = 128, num_classes: int = 2, dropout: float = 0.3):
        super().__init__()
        self.n_mels = n_mels

        self.features = nn.Sequential(
            # Block 1
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(dropout * 0.5),

            # Block 2
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(dropout * 0.5),

            # Block 3
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(dropout),

            # Block 4
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((4, 4)),
        )

        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 4 * 4, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim == 3:
            x = x.unsqueeze(1)  # (batch, time, mels) -> (batch, 1, time, mels)
        x = self.features(x)
        x = self.classifier(x)
        return x

    def get_logits(self, x: torch.Tensor) -> torch.Tensor:
        """Return raw logits (before softmax)."""
        return self(x)


class ResNetDeepfakeDetector(nn.Module):
    """
    ResNet18-based detector with grayscale input adaptation.
    Uses pretrained ImageNet weights and fine-tunes.
    """

    def __init__(self, num_classes: int = 2, pretrained: bool = True):
        super().__init__()
        self.backbone = models.resnet18(
            weights=models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        )
        # Adapt first conv for single-channel input
        self.backbone.conv1 = nn.Conv2d(
            1, 64, kernel_size=7, stride=2, padding=3, bias=False
        )
        self.backbone.fc = nn.Linear(self.backbone.fc.in_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim == 3:
            x = x.unsqueeze(1)
        return self.backbone(x)


# ============================================================
# Option B: Wav2Vec2 with Classification Head
# ============================================================


class Wav2VecDeepfakeDetector(nn.Module):
    """
    Fine-tunes Wav2Vec2 with a classification head.
    Freezes early layers, fine-tunes later ones.
    """

    def __init__(
        self,
        model_name: str = "facebook/wav2vec2-base",
        num_classes: int = 2,
        freeze_base: bool = False,
        freeze_layers: int = 6,
        dropout: float = 0.3,
    ):
        super().__init__()
        from transformers import Wav2Vec2Model

        self.wav2vec = Wav2Vec2Model.from_pretrained(model_name)
        hidden_size = self.wav2vec.config.hidden_size  # 768 for base

        # Freeze early transformer layers
        if freeze_base:
            for param in self.wav2vec.parameters():
                param.requires_grad = False
        elif freeze_layers > 0:
            for layer in self.wav2vec.encoder.layer[:freeze_layers]:
                for param in layer.parameters():
                    param.requires_grad = False

        self.classifier = nn.Sequential(
            nn.Linear(hidden_size, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(256, 64),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(64, num_classes),
        )

    def forward(self, input_values: torch.Tensor) -> torch.Tensor:
        """
        input_values: (batch, sequence_length) raw waveform
        """
        outputs = self.wav2vec(input_values, output_hidden_states=True)
        # Mean pool over time dimension
        hidden = outputs.last_hidden_state.mean(dim=1)  # (batch, hidden_size)
        logits = self.classifier(hidden)
        return logits


# ============================================================
# Temperature Scaling for Calibration
# ============================================================


class TemperatureScaler(nn.Module):
    """
    Post-hoc temperature scaling for probability calibration.
    Learns a single temperature parameter T to soften/harden logits.
    """

    def __init__(self):
        super().__init__()
        self.temperature = nn.Parameter(torch.ones(1) * 1.5)

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        return logits / self.temperature

    def calibrate(self, logits: torch.Tensor, labels: torch.Tensor, lr: float = 0.01, max_iter: int = 100):
        """
        Find optimal temperature by minimizing NLL on validation set.
        """
        self.train()
        optimizer = torch.optim.LBFGS([self.temperature], lr=lr, max_iter=max_iter)
        criterion = nn.CrossEntropyLoss()

        def eval_step():
            optimizer.zero_grad()
            scaled = self.forward(logits)
            loss = criterion(scaled, labels)
            loss.backward()
            return loss

        optimizer.step(eval_step)
        self.eval()
        print(f"  Calibrated temperature: {self.temperature.item():.3f}")


# ============================================================
# Model Factory
# ============================================================


def create_model(
    model_type: str = "cnn",
    num_classes: int = 2,
    **kwargs,
) -> nn.Module:
    """
    Create a model by type name.
    model_type: "cnn", "resnet", "wav2vec"
    """
    if model_type == "cnn":
        return DeepfakeCNN(num_classes=num_classes, **kwargs)
    elif model_type == "resnet":
        return ResNetDeepfakeDetector(num_classes=num_classes, **kwargs)
    elif model_type == "wav2vec":
        return Wav2VecDeepfakeDetector(num_classes=num_classes, **kwargs)
    else:
        raise ValueError(f"Unknown model type: {model_type}")

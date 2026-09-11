#!/usr/bin/env bash
# ============================================================
# Audio Deepfake Detector — Startup Script
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  Audio Deepfake & Synthetic Media Detector${NC}"
echo -e "${CYAN}  Government Communications Security Tool${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# Check for virtual environment
if [ -d "venv" ]; then
    echo -e "${GREEN}[1/4]${NC} Activating virtual environment..."
    source venv/bin/activate
else
    echo -e "${YELLOW}[1/4]${NC} No virtual environment found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    echo -e "${GREEN}[1/4]${NC} Installing dependencies..."
    pip install --retries 3 -r requirements.txt edge-tts 2>/dev/null || true
fi

# Check for trained model
echo -e "${GREEN}[2/4]${NC} Checking model status..."
if [ -f "checkpoints/best_model.pt" ]; then
    echo -e "  ✅ Trained model found at checkpoints/best_model.pt"
else
    echo -e "  ⚠️  No trained model found — will use heuristic mode"
    echo -e "  To train: ${CYAN}python train_full.py --model_type cnn --epochs 30${NC}"
fi

# Generate demo clips if missing
echo -e "${GREEN}[3/4]${NC} Checking demo clips..."
CLIP_COUNT=$(ls demo_clips/*.wav 2>/dev/null | wc -l)
if [ "$CLIP_COUNT" -eq 0 ]; then
    echo -e "  Generating demo clips..."
    python setup_demo.py 2>/dev/null || true
fi
echo -e "  📂 $(ls demo_clips/*.wav 2>/dev/null | wc -l) demo clips available"

# Check for training data
echo -e "${GREEN}[4/4]${NC} Checking training data..."
REAL_COUNT=$(ls data/real/*.wav data/real/*.mp3 data/real/*.flac 2>/dev/null | wc -l 2>/dev/null || echo 0)
FAKE_COUNT=$(ls data/fake/*.wav data/fake/*.mp3 data/fake/*.flac 2>/dev/null | wc -l 2>/dev/null || echo 0)
echo -e "  📁 Real audio: ${CYAN}${REAL_COUNT}${NC} files"
echo -e "  📁 Fake audio: ${CYAN}${FAKE_COUNT}${NC} files"

if [ "$REAL_COUNT" -eq 0 ] && [ "$FAKE_COUNT" -eq 0 ]; then
    echo -e "  ${YELLOW}⚠️  No training data found. Generating synthetic data...${NC}"
    python generate_synthetic.py 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Starting web dashboard on http://localhost:9011${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""

# Start the Flask app
python web_app.py

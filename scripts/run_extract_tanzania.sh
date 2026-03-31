#!/bin/bash
set -e


REPO_DIR="/lightscratch/users/yiren/mamai-medical-guidelines"
LOG_FILE="$REPO_DIR/processed/tanzania_extraction.log"
mkdir -p "$REPO_DIR/processed"

cd "$REPO_DIR"

echo "[$(date +%H:%M:%S)] Starting Tanzania/Zanzibar extraction..."
nvidia-smi || echo "WARNING: no GPU detected"

python scripts/extract_tanzania.py --workers 4 2>&1 | tee "$LOG_FILE"

echo "[$(date +%H:%M:%S)] Done."

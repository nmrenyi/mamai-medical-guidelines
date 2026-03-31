#!/bin/bash
set -e

# --- Phase 1: Root setup (runs as root before NFS-squashed operations) ---

# Add yiren to /etc/passwd so Python/PyTorch can resolve the uid
echo "yiren:x:296712:84257:yiren:/home/yiren:/bin/bash" >> /etc/passwd
mkdir -p /home/yiren

# Install Python + pip
apt-get update -qq && apt-get install -y -qq python3 python3-pip > /dev/null 2>&1
echo "[$(date +%H:%M:%S)] Python installed: $(python3 --version)"

# Install marker-pdf (as root, into system site-packages)
echo "[$(date +%H:%M:%S)] Installing marker-pdf..."
pip install marker-pdf 2>&1 | tail -5
echo "[$(date +%H:%M:%S)] marker-pdf installed"

# Install pandoc + LibreOffice for Tanzania Word doc (.doc/.docx) conversion
echo "[$(date +%H:%M:%S)] Installing pandoc and LibreOffice..."
apt-get install -y -qq pandoc libreoffice > /dev/null 2>&1
echo "[$(date +%H:%M:%S)] pandoc $(pandoc --version | head -1) installed"

# --- Phase 2: Run extraction as yiren (for NFS file access) ---

REPO_DIR="/lightscratch/users/yiren/mamai-medical-guidelines"
WORKERS=10
LOG_FILE="$REPO_DIR/processed/extraction.log"

su yiren -s /bin/bash -c "
set -e
mkdir -p $REPO_DIR/processed

echo '============================================'
echo '  PDF Extraction Job'
echo '  Started: $(date)'
echo '  Workers: $WORKERS'
echo '============================================'

nvidia-smi || echo 'WARNING: no GPU detected'

echo ''
echo '[\$(date +%H:%M:%S)] Starting international guidelines extraction...'
cd $REPO_DIR
python3 scripts/extract_to_markdown.py --workers $WORKERS 2>&1 | tee $LOG_FILE

echo ''
echo '[\$(date +%H:%M:%S)] Starting Tanzania/Zanzibar guidelines extraction...'
python3 scripts/extract_tanzania.py --workers $WORKERS 2>&1 | tee -a $LOG_FILE

echo ''
echo '============================================'
echo '  Finished: \$(date)'
echo '============================================'
"

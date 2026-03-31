#!/bin/bash
# Submit the PDF extraction job to the LiGHT cluster via run:ai.
# Run this from your local terminal (requires runai CLI configured).
#
# Usage:
#   bash scripts/submit_extraction.sh
#
# Monitor:
#   runai logs mamai-extract-intl -f

set -e

JOB_NAME="mamai-extract-intl"
IMAGE="registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest"
PROJECT="light-yiren"
REPO_DIR="/lightscratch/users/yiren/mamai-medical-guidelines"
SERVER_SCRIPTS="light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/scripts"

# Delete previous job if it exists (runai doesn't allow reusing names)
runai delete job "$JOB_NAME" 2>/dev/null || true

# Sync latest scripts to the server before submitting so the job runs
# the current code without needing git credentials inside the container.
echo "Syncing scripts to server..."
scp scripts/extract_to_markdown.py scripts/extract_tanzania.py \
    scripts/exclusions.py scripts/run_extraction.sh \
    "$SERVER_SCRIPTS/"

echo "Submitting job: $JOB_NAME"

runai submit "$JOB_NAME" \
  --image "$IMAGE" \
  --pvc light-scratch:/lightscratch \
  --gpu 1 \
  --cpu 12 --cpu-limit 12 \
  --memory 64G --memory-limit 64G \
  --large-shm \
  --node-pool h100 \
  --project "$PROJECT" \
  --run-as-uid 296712 \
  --run-as-gid 84257 \
  -e SKIP_INSTALL_PROJECT=1 \
  -e PYTHONUSERBASE=/lightscratch/users/yiren/.local \
  -- bash -c "
    pip install --user marker-pdf -q 2>&1 | tail -3 &&
    cd /lightscratch/users/yiren/mamai-medical-guidelines &&
    python3 scripts/extract_to_markdown.py --workers 4 &&
    python3 scripts/extract_tanzania.py --workers 4
  "

echo ""
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"

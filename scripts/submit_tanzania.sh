#!/bin/bash
# Submit the Tanzania PDF extraction job to the LiGHT cluster via run:ai.
# Run this from your local terminal (requires runai CLI configured).
#
# Usage:
#   bash scripts/submit_tanzania.sh
#
# Monitor:
#   runai logs mamai-extract-tz -f

set -e

JOB_NAME="mamai-extract-tz"
IMAGE="registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest"
PROJECT="light-yiren"
SERVER_SCRIPTS="light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/scripts"

# Delete previous job if it exists
runai delete job "$JOB_NAME" 2>/dev/null || true

# Sync latest scripts to the server
echo "Syncing scripts to server..."
scp scripts/extract_tanzania.py scripts/exclusions.py "$SERVER_SCRIPTS/"

echo "Submitting job: $JOB_NAME"

runai submit "$JOB_NAME" \
  --image "$IMAGE" \
  --pvc light-scratch:/lightscratch \
  --gpu 1 \
  --cpu 8 --cpu-limit 8 \
  --memory 32G --memory-limit 32G \
  --large-shm \
  --node-pool h100 \
  --project "$PROJECT" \
  --run-as-uid 296712 \
  --run-as-gid 84257 \
  -e SKIP_INSTALL_PROJECT=1 \
  -e FONT_PATH=/tmp/marker/GoNotoCurrent-Regular.ttf \
  -- bash -c "
    cd /lightscratch/users/yiren/mamai-medical-guidelines &&
    python3 scripts/extract_tanzania.py --workers 4 --force
  "

echo ""
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"

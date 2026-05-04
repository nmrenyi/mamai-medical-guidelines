#!/bin/bash
# Submit a PDF extraction job for a raw/ subdirectory to the LiGHT cluster.
#
# Usage:
#   bash scripts/submit_extraction_dir.sh <subdir>
#
# Examples:
#   bash scripts/submit_extraction_dir.sh open-books
#   bash scripts/submit_extraction_dir.sh exams
#   bash scripts/submit_extraction_dir.sh whole-books
#
# Monitor:
#   runai logs mamai-extract-<subdir> -f
#
# Download results when done:
#   bash scripts/download_results.sh <subdir>

set -e

SUBDIR="${1:?Usage: bash scripts/submit_extraction_dir.sh <subdir>}"

JOB_NAME="mamai-extract-$SUBDIR"
IMAGE="registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest"
PROJECT="light-yiren"
SERVER="light"
SERVER_ROOT="$SERVER:/mnt/light/scratch/users/yiren/mamai-medical-guidelines"

# Delete previous job with the same name if it exists
runai delete job "$JOB_NAME" 2>/dev/null || true

# Sync the raw/<subdir>/ PDFs to the cluster
echo "Syncing raw/$SUBDIR/ to cluster..."
rsync -av --mkpath "raw/$SUBDIR/" "$SERVER_ROOT/raw/$SUBDIR/"

# Sync the extraction script
echo "Syncing scripts to server..."
scp scripts/extract_dir.py "$SERVER_ROOT/scripts/"

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
  -e FONT_PATH=/tmp/marker/GoNotoCurrent-Regular.ttf \
  -- bash -c "
    cd /lightscratch/users/yiren/mamai-medical-guidelines &&
    python3 scripts/extract_dir.py \
      --input-dir raw/$SUBDIR \
      --output-dir processed/extracted/international \
      --workers 4
  "

echo ""
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"
echo ""
echo "To download results when done:"
echo "  bash scripts/download_results.sh $SUBDIR"

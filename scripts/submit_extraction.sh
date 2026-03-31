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

# Delete previous job if it exists (runai doesn't allow reusing names)
runai delete job "$JOB_NAME" 2>/dev/null || true

echo "Submitting job: $JOB_NAME"

runai submit "$JOB_NAME" \
  --image "$IMAGE" \
  --pvc light-scratch:/lightscratch \
  --gpu 1 \
  --project "$PROJECT" \
  -- bash -c "cd $REPO_DIR && git pull && bash scripts/run_extraction.sh"

echo ""
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"

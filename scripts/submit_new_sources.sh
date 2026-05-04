#!/bin/bash
# Submit new-source extraction job to the LiGHT cluster via run:ai.
# Extracts PDFs from raw/open-books/ (add --also-exams / --also-whole-books as needed).
#
# Run from your local terminal (requires runai CLI and ssh access to light).
#
# Usage:
#   bash scripts/submit_new_sources.sh
#
# Monitor:
#   runai logs mamai-extract-new -f
#
# Pull results when done:
#   rsync -av --include="*.md" --exclude="*/" \
#     "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/extracted/international/" \
#     "processed/extracted/international/"

set -e

JOB_NAME="mamai-extract-new"
IMAGE="registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest"
PROJECT="light-yiren"
REPO_DIR="/lightscratch/users/yiren/mamai-medical-guidelines"
SERVER="light"
SERVER_SCRIPTS="$SERVER:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/scripts"
SERVER_RAW="$SERVER:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/raw"

# Delete previous job if it exists
runai delete job "$JOB_NAME" 2>/dev/null || true

# Sync new PDFs to the cluster
echo "Syncing raw/open-books/ to cluster..."
rsync -av --mkpath raw/open-books/ "$SERVER_RAW/open-books/"

# Uncomment to also sync exams/ or whole-books/:
# echo "Syncing raw/exams/ to cluster..."
# rsync -av --mkpath raw/exams/ "$SERVER_RAW/exams/"
# echo "Syncing raw/whole-books/ to cluster..."
# rsync -av --mkpath raw/whole-books/ "$SERVER_RAW/whole-books/"

# Sync the new extraction script
echo "Syncing scripts to server..."
scp scripts/extract_new_sources.py "$SERVER_SCRIPTS/"

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
    python3 scripts/extract_new_sources.py --workers 4
  "

echo ""
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"
echo ""
echo "When done, pull results:"
echo "  rsync -av --include='*.md' --exclude='*/' \\"
echo "    '$SERVER:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/extracted/international/' \\"
echo "    'processed/extracted/international/'"

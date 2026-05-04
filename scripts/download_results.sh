#!/bin/bash
# Check the status of a extraction job and download results if finished.
#
# Usage:
#   bash scripts/download_results.sh <subdir>
#
# Examples:
#   bash scripts/download_results.sh open-books
#   bash scripts/download_results.sh exams

set -e

SUBDIR="${1:?Usage: bash scripts/download_results.sh <subdir>}"

JOB_NAME="mamai-extract-$SUBDIR"
SERVER="light"
SERVER_ROOT="$SERVER:/mnt/light/scratch/users/yiren/mamai-medical-guidelines"

echo "Checking status of job: $JOB_NAME"
STATUS=$(runai describe job "$JOB_NAME" --output json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('status', {}).get('state', 'UNKNOWN'))
" 2>/dev/null || echo "NOT_FOUND")

echo "Status: $STATUS"

case "$STATUS" in
  Succeeded)
    echo ""
    echo "Job finished successfully. Downloading results..."
    rsync -av --include="*.md" --exclude="*/" \
      "$SERVER_ROOT/processed/extracted/international/" \
      "processed/extracted/international/"
    echo ""
    echo "Done. Run the following to continue the pipeline:"
    echo "  make processed/normalized"
    echo "  make processed/chunks_for_rag.txt"
    ;;
  Failed)
    echo ""
    echo "Job failed. Check logs for details:"
    echo "  runai logs $JOB_NAME"
    exit 1
    ;;
  Running|Pending)
    echo ""
    echo "Job is still running. Check logs:"
    echo "  runai logs $JOB_NAME -f"
    ;;
  NOT_FOUND)
    echo ""
    echo "Job not found in Run:ai (may have completed and been cleaned up)."
    echo "Attempting to download results anyway..."
    rsync -av --include="*.md" --exclude="*/" \
      "$SERVER_ROOT/processed/extracted/international/" \
      "processed/extracted/international/"
    echo ""
    echo "Done. Run the following to continue the pipeline:"
    echo "  make processed/normalized"
    echo "  make processed/chunks_for_rag.txt"
    ;;
  *)
    echo ""
    echo "Unexpected status. Check manually:"
    echo "  runai describe job $JOB_NAME"
    exit 1
    ;;
esac

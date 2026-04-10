#!/bin/bash
# Submit the embedding build to the LiGHT cluster via run:ai.
# Run this from your local terminal (requires runai CLI configured).
#
# Usage:
#   bash scripts/submit_embeddings.sh
#
# Optional environment overrides:
#   JOB_NAME=mamai-embed
#   IMAGE=registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest
#   PROJECT=light-yiren
#   CPU=24
#   MEMORY=64G
#   WORKERS=6
#   SMOKE_CHUNKS=200
#   NODE_POOL=cpu
#   LOCAL_GECKO=/abs/path/Gecko_1024_quant.tflite
#   LOCAL_TOKENIZER=/abs/path/sentencepiece.model
#
# Monitor:
#   runai logs mamai-embed -f

set -euo pipefail

JOB_NAME="${JOB_NAME:-mamai-embed}"
IMAGE="${IMAGE:-registry.rcp.epfl.ch/light/yiren/mamai-guidelines:amd64-cuda-yiren-latest}"
PROJECT="${PROJECT:-light-yiren}"
CPU="${CPU:-24}"
MEMORY="${MEMORY:-64G}"
WORKERS="${WORKERS:-6}"
SMOKE_CHUNKS="${SMOKE_CHUNKS:-200}"
NODE_POOL="${NODE_POOL:-}"

LOCAL_GECKO="${LOCAL_GECKO:-/Users/renyi/Downloads/mamai/app/model_backup/Gecko_1024_quant.tflite}"
LOCAL_TOKENIZER="${LOCAL_TOKENIZER:-/Users/renyi/Downloads/mamai/app/model_backup/sentencepiece.model}"

REPO_DIR="/lightscratch/users/yiren/mamai-medical-guidelines"
SERVER_ROOT="light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines"
SERVER_SCRIPTS="$SERVER_ROOT/scripts"
SERVER_PROCESSED="$SERVER_ROOT/processed"
SERVER_MODELS="$SERVER_ROOT/model_backup"

REMOTE_GECKO="$REPO_DIR/model_backup/Gecko_1024_quant.tflite"
REMOTE_TOKENIZER="$REPO_DIR/model_backup/sentencepiece.model"

if [[ ! -f "$LOCAL_GECKO" ]]; then
  echo "ERROR: Gecko model not found: $LOCAL_GECKO" >&2
  exit 1
fi

if [[ ! -f "$LOCAL_TOKENIZER" ]]; then
  echo "ERROR: Tokenizer not found: $LOCAL_TOKENIZER" >&2
  exit 1
fi

if [[ ! -f "processed/chunks_for_rag.txt" ]]; then
  echo "ERROR: Chunk file not found: processed/chunks_for_rag.txt" >&2
  exit 1
fi

echo "Preparing cluster directories..."
ssh light "mkdir -p \
  /mnt/light/scratch/users/yiren/mamai-medical-guidelines/scripts \
  /mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed \
  /mnt/light/scratch/users/yiren/mamai-medical-guidelines/model_backup"

echo "Syncing scripts, chunks, and model files to server..."
scp \
  scripts/build_embeddings.py \
  scripts/embed_parallel.py \
  scripts/run_embeddings.sh \
  "$SERVER_SCRIPTS/"
scp \
  processed/chunks_for_rag.txt \
  "$SERVER_PROCESSED/"
scp \
  "$LOCAL_GECKO" \
  "$LOCAL_TOKENIZER" \
  "$SERVER_MODELS/"

runai delete job "$JOB_NAME" 2>/dev/null || true

RUNAI_ARGS=(
  submit "$JOB_NAME"
  --image "$IMAGE"
  --pvc light-scratch:/lightscratch
  --cpu "$CPU" --cpu-limit "$CPU"
  --memory "$MEMORY" --memory-limit "$MEMORY"
  --large-shm
  --project "$PROJECT"
  --run-as-uid 296712
  --run-as-gid 84257
)

if [[ -n "$NODE_POOL" ]]; then
  RUNAI_ARGS+=(--node-pool "$NODE_POOL")
fi

echo "Submitting job: $JOB_NAME"
runai "${RUNAI_ARGS[@]}" -- \
  bash "$REPO_DIR/scripts/run_embeddings.sh" \
  "$REPO_DIR" \
  "$REMOTE_GECKO" \
  "$REMOTE_TOKENIZER" \
  "$WORKERS" \
  "$SMOKE_CHUNKS"

echo
echo "Job submitted. To monitor:"
echo "  runai logs $JOB_NAME -f"
echo
echo "When it finishes, copy the SQLite back with:"
echo "  scp light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/embeddings.sqlite processed/"

#!/bin/bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "Usage: bash scripts/run_embeddings.sh SOURCE_REPO_DIR GECKO TOKENIZER WORKERS SMOKE_CHUNKS" >&2
  exit 1
fi

SOURCE_REPO_DIR="$1"
GECKO_PATH="$2"
TOKENIZER_PATH="$3"
WORKERS="$4"
SMOKE_CHUNKS="$5"

WORK_DIR="/home/runai-home/mamai-embed"
LOCAL_GECKO="$WORK_DIR/model_backup/Gecko_1024_quant.tflite"
LOCAL_TOKENIZER="$WORK_DIR/model_backup/sentencepiece.model"
LOCAL_CHUNKS="$WORK_DIR/processed/chunks_for_rag.txt"
LOCAL_SMOKE_DB="$WORK_DIR/processed/embeddings_smoke.sqlite"
LOCAL_OUTPUT_DB="$WORK_DIR/processed/embeddings.sqlite"
REMOTE_SMOKE_DB="$SOURCE_REPO_DIR/processed/embeddings_smoke.sqlite"
REMOTE_OUTPUT_DB="$SOURCE_REPO_DIR/processed/embeddings.sqlite"

mkdir -p "$WORK_DIR/scripts" "$WORK_DIR/processed" "$WORK_DIR/model_backup"

echo "[$(date +%H:%M:%S)] Staging inputs to local pod storage..."
cp "$SOURCE_REPO_DIR/scripts/build_embeddings.py" "$WORK_DIR/scripts/"
cp "$SOURCE_REPO_DIR/scripts/embed_parallel.py" "$WORK_DIR/scripts/"
cp "$SOURCE_REPO_DIR/processed/chunks_for_rag.txt" "$LOCAL_CHUNKS"
cp "$GECKO_PATH" "$LOCAL_GECKO"
cp "$TOKENIZER_PATH" "$LOCAL_TOKENIZER"
echo "[$(date +%H:%M:%S)] Staging complete."

cd "$WORK_DIR"

python3 -u - <<'PY'
import importlib.util
import subprocess
import sys


def has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


missing = []
if not has("numpy"):
    missing.append("numpy")
if not has("sentencepiece"):
    missing.append("sentencepiece")
if not (has("ai_edge_litert") or has("tensorflow") or has("tflite_runtime")):
    missing.append("ai-edge-litert")

print("Dependency check:")
print("  numpy:", has("numpy"))
print("  sentencepiece:", has("sentencepiece"))
print("  ai_edge_litert:", has("ai_edge_litert"))
print("  tensorflow:", has("tensorflow"))
print("  tflite_runtime:", has("tflite_runtime"))

if missing:
    print("Installing missing packages:", ", ".join(missing))
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", *missing])
PY

echo
echo "[$(date +%H:%M:%S)] Starting embedding smoke test..."
python3 scripts/build_embeddings.py \
  --chunks "$LOCAL_CHUNKS" \
  --gecko "$LOCAL_GECKO" \
  --tokenizer "$LOCAL_TOKENIZER" \
  --output "$LOCAL_SMOKE_DB" \
  --end-chunk "$SMOKE_CHUNKS" \
  --num-threads 2
cp "$LOCAL_SMOKE_DB" "$REMOTE_SMOKE_DB"

echo
echo "[$(date +%H:%M:%S)] Starting full embedding build..."
python3 scripts/embed_parallel.py \
  --chunks "$LOCAL_CHUNKS" \
  --gecko "$LOCAL_GECKO" \
  --tokenizer "$LOCAL_TOKENIZER" \
  --output "$LOCAL_OUTPUT_DB" \
  --workers "$WORKERS"
cp "$LOCAL_OUTPUT_DB" "$REMOTE_OUTPUT_DB"

echo
echo "[$(date +%H:%M:%S)] Embedding job finished."

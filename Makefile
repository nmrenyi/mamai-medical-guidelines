PYTHON := python3

# ── Outputs ───────────────────────────────────────────────────────────────────
EXTRACTED  := processed/extracted
NORMALIZED := processed/normalized
CHUNKS     := processed/chunks_for_rag.txt
EMBEDDINGS := processed/embeddings.sqlite

# ── Pipeline ──────────────────────────────────────────────────────────────────
# Step 1 — PDF → Markdown  (LiGHT cluster, not automated here)
#   bash scripts/submit_extraction.sh
#   bash scripts/submit_tanzania.sh
#   rsync results to processed/extracted/  — see README

# Step 2 — strip HTML spans from extracted markdowns
$(NORMALIZED): $(EXTRACTED)
	$(PYTHON) scripts/strip_spans.py

# Step 3 — chunk normalized markdowns into RAG passages
$(CHUNKS): $(NORMALIZED)
	$(PYTHON) scripts/chunk_guidelines.py

# Step 4 — generate Gecko embeddings
$(EMBEDDINGS): $(CHUNKS)
	$(PYTHON) scripts/build_embeddings.py

# ── Utilities ─────────────────────────────────────────────────────────────────
.PHONY: all clean help

all: $(EMBEDDINGS)

clean:
	rm -rf $(NORMALIZED) $(CHUNKS) $(EMBEDDINGS)

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "  all      Run full local pipeline: normalize → chunk → embed (default)"
	@echo "  clean    Remove generated files (normalized/, chunks, embeddings)"
	@echo "  help     Show this help"
	@echo ""
	@echo "Note: Step 1 (PDF → extracted/) runs on the LiGHT cluster — see README."

# MAMAI Medical Guidelines

Guidelines for the RAG system of the [MAMAI project](https://github.com/nmrenyi/mamai).

Raw data shared by Trevor Brokowski via [Google Drive](https://drive.google.com/drive/folders/1urBQnXJaay8AlhqQPtcVjWuqZUiFcvOK). Place both folders under `raw/`.

---

## Repository Structure

```
raw/
  Clinical guidelines_International/      # 39 international guideline PDFs (gitignored)
  Clinical guidelines_Zanzibar-Tanzania/  # 19 Tanzania/Zanzibar guideline PDFs (gitignored)

scripts/
  extract_to_markdown.py   # [step 1] convert international PDFs → markdown via marker-pdf
  extract_tanzania.py      # [step 1] convert Tanzania PDFs → markdown via marker-pdf
  submit_extraction.sh     # run international extraction on LiGHT H100 cluster
  submit_tanzania.sh       # run Tanzania extraction on LiGHT H100 cluster
  exclusions.py            # PDFs to skip or deduplicate
  strip_spans.py           # [step 2] strip HTML span tags from extracted markdowns
  chunk_guidelines.py      # [step 3] chunk normalized markdowns into RAG passages
  build_embeddings.py      # [step 4] embed chunks with Gecko TFLite model

Makefile                   # orchestrates steps 2–4 (step 1 runs on cluster)

processed/                 # gitignored — generated outputs
  extracted/
    international/         # [step 1] 39 marker-pdf markdowns, one per PDF
    tanzania/              # [step 1] 18 marker-pdf markdowns, one per PDF
  normalized/
    international/         # [step 2] span-stripped markdowns
    tanzania/              # [step 2] span-stripped markdowns
  chunks_for_rag.txt       # [step 3] RAG passages with source/page metadata
  embeddings.sqlite        # [step 4] Gecko embeddings for on-device search
  legacy_pymupdf/          # deprecated PyMuPDF outputs (stale, kept for reference)
```

---

## Pipeline

### Step 1 — PDF → Markdown (done)

PDFs are converted to structured markdown using [marker-pdf](https://github.com/VikParuchuri/marker), an ML-based converter that recovers headings, tables, and lists. Each `.md` file contains `<!-- page: N -->` markers aligned to physical PDF page numbers (verified: exact match across all 58 files).

**Run on LiGHT cluster (EPFL) via run:ai:**

```bash
bash scripts/submit_extraction.sh   # international (39 PDFs)
bash scripts/submit_tanzania.sh     # Tanzania (19 PDFs)
```

Monitor:
```bash
runai logs mamai-extract-intl -f
runai logs mamai-extract-tz -f
```

Pull results:
```bash
rsync -av --include="*.md" --exclude="tanzania/" --exclude="*/" \
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/extracted/" \
  "processed/extracted/international/"

rsync -av \
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/extracted/tanzania/" \
  "processed/extracted/tanzania/"
```

### Step 2 — Normalize (TODO)

Strip HTML span tags left by marker-pdf from the extracted markdowns:

```bash
make processed/normalized
# or: python scripts/strip_spans.py
```

Reads from `processed/extracted/`, writes to `processed/normalized/`. Originals are not modified.

### Step 3 — Markdown → Chunks (TODO)

Chunk the normalized markdowns into RAG passages:

```bash
make processed/chunks_for_rag.txt
# or: python scripts/chunk_guidelines.py
```

**File selection logic:**
- **International** (39 PDFs): only the 24 HIGH-relevance files are included by default; executive summaries that duplicate full guidelines are also skipped. Pass `--all` to include everything.
- **Tanzania** (18 PDFs): all files are always included — no relevance filtering, since these are regional guidelines specifically relevant to the deployment context.

### Step 4 — Chunks → Embeddings (TODO)

```bash
make  # runs the full local pipeline (steps 2–4)
# or: python scripts/build_embeddings.py
```

---

## marker-pdf vs PyMuPDF

| | marker-pdf (current) | PyMuPDF (deprecated) |
|---|---|---|
| Text quality | ML-based: recovers structure (headings, tables, lists) | Raw character stream, no structure |
| Tables | Reconstructed as markdown tables | Flattened or garbled |
| Page accuracy | Exact match to PDF page count (verified) | Accurate |
| Speed | Slow — GPU required | Fast — CPU only |
| Output | `processed/markdowns/` (intermediate markdown) | Chunks directly |

---

## Notes

- `exclusions.py` lists PDFs skipped during extraction (duplicates, non-English)
- `extract_tanzania.py --force` re-extracts even if output already exists
- Cluster jobs run as uid=296712 with `FONT_PATH=/tmp/marker/...` to avoid a write-permission issue in the system packages directory

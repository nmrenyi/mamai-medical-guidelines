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

**Chunking strategy (default: `structured`)**

Clinical guidelines are structured documents — a heading signals a new topic, not a page break. The default strategy exploits this: it splits on headings and treats page boundaries as citation metadata only. This keeps each recommendation, procedure, or section intact as a single retrieval unit, even when it spans multiple PDF pages.

The pipeline:

1. **Parse into sections** — the markdown is scanned line by line. Any ATX heading (`#`–`######`) or standalone `**bold line**` (≥ 3 words) opens a new section. All content until the next heading belongs to that section.

2. **Track pages as metadata** — `<!-- page: N -->` markers are consumed during parsing and attached per-line. Each chunk records `page_start` from its first content line. Page boundaries never force a split.

3. **Filter boilerplate** — sections are discarded if their heading matches patterns like "contents", "acknowledgements", "references", "foreword", or if the body looks like a table of contents (lines ending in page numbers). This removes front/back matter with no clinical value.

4. **Emit or subdivide by size**:
   - Section ≤ 1500 chars → emitted as one chunk
   - Section > 1500 chars → each block type is split independently, then pieces are greedily packed into chunks up to 800 chars:
     - **Tables**: split by row groups, repeating the header row on each piece
     - **Lists**: split at top-level item boundaries
     - **Paragraphs**: split at `\n\n` breaks
     - **Fallback**: overlapping 800-char windows with 100-char overlap

   Example — a section containing 1000-char paragraph + 2000-char table + 3000-char list:
   ```
   paragraph (1000) → 2 pieces × ~500 chars
   table (2000)     → N row groups × ≤800 chars, each repeating the header
   list (3000)      → M item groups × ≤800 chars
   ```
   Each piece is then packed with its neighbors: if two consecutive pieces fit within 800 chars they are merged into one chunk (marked `mixed`); otherwise each becomes its own chunk. Every chunk gets the section heading prepended.

5. **Prepend parent breadcrumb** — each chunk is prefixed with its ancestor heading path so it is self-contained for retrieval. A leaf-level chunk under `Recommendations > 1.2 Service organisation` becomes:
   ```
   > Recommendations > 1.2 Service organisation

   ### All women at low risk of complications
   - 1.3.1 Explain to both multiparous and nulliparous women...
   ```
   This lets a query for a broad topic (e.g. "service organisation") match leaf-level chunks that would otherwise lack the parent context. Top-level sections (no parent) get no breadcrumb.

6. **Write output** — every chunk is written as:
   ```
   <sep>[SOURCE:NICE_intrapartum_2023|PAGE:14]
   > Recommendations > 1.2 Service organisation

   ### All women at low risk of complications
   Women should be offered...
   ```
   The `<sep>` delimiter and `[SOURCE:|PAGE:]` prefix are parsed by `RagPipeline.kt` in the Android app.

Use `--jsonl-sidecar <path>` to write a JSONL file with richer metadata per chunk (section path, chunk type, page range) for debugging or evaluation.

**File selection:** all 39 international and 18 Tanzania files are included. The only exclusions are executive summaries that duplicate full guidelines (`SKIP_FILES` in the script). Relevance filtering is left to the retrieval system at query time.

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
| Output | `processed/extracted/` then `processed/normalized/` | Chunks directly |

---

## Notes

- `exclusions.py` lists PDFs skipped during extraction (duplicates, non-English)
- `extract_tanzania.py --force` re-extracts even if output already exists
- Cluster jobs run as uid=296712 with `FONT_PATH=/tmp/marker/...` to avoid a write-permission issue in the system packages directory

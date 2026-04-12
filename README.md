# MAMAI Medical Guidelines

Guidelines processing pipeline for the [MAMAI project](https://github.com/nmrenyi/mamai) — converts raw clinical guideline PDFs into a versioned RAG bundle that the Android app consumes.

Raw data shared by Trevor Brokowski via [Google Drive](https://drive.google.com/drive/folders/1urBQnXJaay8AlhqQPtcVjWuqZUiFcvOK). Place both folders under `raw/`.

---

## Data Flow Overview

```
raw/*.pdf
    │
    │  [Step 1 — LiGHT H100 cluster]
    ▼
processed/extracted/          marker-pdf markdown, one file per PDF
    │
    │  [Step 2 — local]
    ▼
processed/normalized/         span-stripped markdowns
    │
    │  [Step 3 — local]
    ▼
processed/chunks_for_rag.txt  21,731 RAG chunks  [SOURCE:stem|PAGE:n]
    │
    │  [Step 4 — LiGHT CPU cluster]
    ▼
processed/embeddings.sqlite   21,731 Gecko embeddings (768-dim, VF32 format)
    │
    │  [Step 5 — local, scripts/package_bundle.py]
    ▼
rag-bundle-<version>/         versioned release bundle
    │
    │  [GitHub Releases]
    ▼
mamai repo — rag-assets.lock.json + scripts/sync_rag_assets.sh
    │
    │  [adb push]
    ▼
Android device — getExternalFilesDir(null)/
```

**Contract across the boundary:** every chunk is prefixed `[SOURCE:<source_id>|PAGE:<n>]`. The `source_id` is the PDF filename stem, normalised to `[A-Za-z0-9\-.]` with underscores replacing all other characters. The bundle ships PDFs under the same normalised name; the app resolves PDF paths using the same rule.

---

## Repository Structure

```
raw/
  Clinical guidelines_International/      # 39 international guideline PDFs (gitignored)
  Clinical guidelines_Zanzibar-Tanzania/  # Tanzania/Zanzibar guideline PDFs (gitignored)

scripts/
  extract_to_markdown.py   # [step 1] convert international PDFs → markdown via marker-pdf
  extract_tanzania.py      # [step 1] convert Tanzania PDFs → markdown via marker-pdf
  submit_extraction.sh     # run international extraction on LiGHT H100 cluster
  submit_tanzania.sh       # run Tanzania extraction on LiGHT H100 cluster
  exclusions.py            # PDFs to skip or deduplicate
  strip_spans.py           # [step 2] strip HTML span tags from extracted markdowns
  chunk_guidelines.py      # [step 3] chunk normalized markdowns into RAG passages
  build_embeddings.py      # [step 4] embed chunks with Gecko TFLite model
  embed_parallel.py        # [step 4] parallel embedding coordinator (N subprocesses)
  submit_embeddings.sh     # run embedding build on LiGHT CPU cluster
  run_embeddings.sh        # cluster worker: stage inputs locally, install deps, embed
  package_bundle.py        # [step 5] package versioned release bundle

Makefile                   # orchestrates steps 2–4 (step 1 and 5 run separately)

processed/                 # gitignored — generated outputs
  extracted/
    international/         # [step 1] marker-pdf markdowns, one per international PDF
    tanzania/              # [step 1] marker-pdf markdowns, one per Tanzania PDF
  normalized/
    international/         # [step 2] span-stripped markdowns
    tanzania/              # [step 2] span-stripped markdowns
  chunks_for_rag.txt       # [step 3] RAG passages with source/page metadata
  embeddings.sqlite        # [step 4] Gecko embeddings for on-device search
  legacy_pymupdf/          # deprecated PyMuPDF outputs (stale, kept for reference)
```

---

## Current Status (2026-04-11)

All steps complete. Bundle v1.0.0 shipped.

| Step | Output | Status |
|------|--------|--------|
| 1 — PDF → Markdown | 39 intl + 18 Tanzania markdowns | ✓ done |
| 2 — Normalize | span-stripped corpus | ✓ done |
| 3 — Chunk | 21,731 chunks in `chunks_for_rag.txt` | ✓ done |
| 4 — Embed | 21,731 rows in `embeddings.sqlite` (validated) | ✓ done |
| 5 — Bundle | [v1.0.0 on GitHub Releases](https://github.com/nmrenyi/mamai-medical-guidelines/releases/tag/v1.0.0) | ✓ done |

---

## Pipeline

### Step 1 — PDF → Markdown

PDFs are converted to structured markdown using [marker-pdf](https://github.com/VikParuchuri/marker), an ML-based converter that recovers headings, tables, and lists. Each `.md` file contains `<!-- page: N -->` markers aligned to physical PDF page numbers.

**Run on LiGHT cluster (EPFL) via run:ai:**

```bash
bash scripts/submit_extraction.sh   # international (39 PDFs)
bash scripts/submit_tanzania.sh     # Tanzania/Zanzibar corpus
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

### Step 2 — Normalize

Strip HTML span tags left by marker-pdf:

```bash
make processed/normalized
# or: python scripts/strip_spans.py
```

Reads from `processed/extracted/`, writes to `processed/normalized/`. Originals are not modified.

### Step 3 — Markdown → Chunks

```bash
make processed/chunks_for_rag.txt
# or: python scripts/chunk_guidelines.py
```

**Chunking strategy**

Clinical guidelines are structured documents — headings signal topic boundaries, not page breaks. The pipeline:

1. **Parse into sections** — ATX headings (`#`–`######`) or standalone `**bold lines**` open new sections. All content until the next heading belongs to that section.

2. **Track pages as metadata** — `<!-- page: N -->` markers are consumed during parsing. Page boundaries never force a split; each chunk records `page_start` from its first content line.

3. **Filter boilerplate** — sections matching patterns like "contents", "acknowledgements", "references", or "foreword" are discarded. Empty bodies, cross-reference stubs, and blank form tables are also dropped.

4. **Emit or subdivide by size** — sections ≤ 1500 chars are emitted as one chunk. Larger sections are split by block type (tables split by row group with header repeat, lists split at item boundaries, paragraphs at `\n\n`), then greedily packed into ≤ 800-char pieces. A hard cap of 2500 chars per chunk is enforced.

5. **Prepend parent breadcrumb** — every piece gets a `> Parent > Child` breadcrumb and its section heading prepended, so every chunk is self-contained for retrieval even when the section was split across multiple pieces.

6. **Deduplicate** — exact-text duplicates across sources are removed before writing output.

Output format:
```
<sep>[SOURCE:NICE_intrapartum_2023|PAGE:14]
> Recommendations > 1.2 Service organisation

### All women at low risk of complications
Women should be offered...
```

Use `--jsonl-sidecar <path>` for a JSONL file with richer metadata per chunk (section path, chunk type, page range).

### Step 4 — Chunks → Embeddings

**Recommended: LiGHT CPU cluster**

```bash
bash scripts/submit_embeddings.sh
```

This job syncs inputs to cluster scratch, runs a 200-chunk smoke test, then runs the full parallel build with `embed_parallel.py` (N subprocesses, each writing a partial SQLite that are merged at the end).

Monitor:
```bash
runai logs mamai-embed -f
```

Pull results:
```bash
scp light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/embeddings.sqlite processed/
```

**Local build (slow, CPU-only):**
```bash
make  # runs steps 2–4
# or: python scripts/build_embeddings.py
```

**Embedding format:** `VF32` magic prefix + 768 × float32 little-endian = 3076 bytes per row. Parsed by Android's `SqliteVectorStore` from the Google AI Edge localagents-rag library.

### Step 5 — Package & Publish Bundle

Once steps 3 and 4 are complete and validated:

```bash
python scripts/package_bundle.py --version v1.1.0 --output-dir /tmp
```

This produces:
```
/tmp/rag-bundle-v1.1.0/
  manifest.json          # full provenance: commit, chunk count, embedding format, per-doc entries
  checksums.sha256       # SHA-256 for every artifact
  runtime/
    embeddings.sqlite    # loaded by the Android app at runtime
  debug/
    chunks_for_rag.txt   # for offline eval
  docs/
    <normalized_id>.pdf  # 55 source PDFs with URL-safe filenames
```

The script resolves every SOURCE id in the chunk file to a raw PDF, normalises the filename, and fails if any mapping is missing. 5 sourceless PDFs (exec summaries, alternate-named duplicates) are excluded automatically.

**Publish to GitHub Releases:**

The script creates the tarball automatically with `COPYFILE_DISABLE=1` so macOS
`._*` / `__MACOSX` metadata entries are never included, then validates the
archive before finishing.

```bash
# The script creates rag-bundle-v1.1.0.tar.gz alongside the bundle dir
python scripts/package_bundle.py --version v1.1.0 --output-dir /tmp

# Upload to GitHub Releases (use the SHA-256 printed by the script for lock.json)
gh release create v1.1.0 /tmp/rag-bundle-v1.1.0.tar.gz \
  --repo nmrenyi/mamai-medical-guidelines \
  --title "RAG Bundle v1.1.0" \
  --notes "..."
```

> **Never** use a bare `tar -czf` on macOS — it embeds `._*` AppleDouble
> sidecar files that break the consumer's PDF count and may crash the Dart tar
> reader. Always let `package_bundle.py` create the archive.

**Then in the `mamai` consumer repo**, bump `rag-assets.lock.json` with the new version, URL, and manifest SHA256, then run:

```bash
bash scripts/sync_rag_assets.sh   # downloads, verifies checksums, stages into device_push/
bash scripts/push_to_device.sh    # pushes staged assets to connected Android device
```

---

## marker-pdf vs PyMuPDF

| | marker-pdf (current) | PyMuPDF (deprecated) |
|---|---|---|
| Text quality | ML-based: recovers headings, tables, lists | Raw character stream, no structure |
| Tables | Reconstructed as markdown tables | Flattened or garbled |
| Page accuracy | Exact match to PDF page count (verified) | Accurate |
| Speed | Slow — GPU required | Fast — CPU only |
| Output | `processed/extracted/` → `processed/normalized/` | Chunks directly |

---

## Notes

- `exclusions.py` lists PDFs skipped during extraction (duplicates, non-English)
- `extract_tanzania.py --force` re-extracts even if output already exists
- Cluster jobs run as uid=296712 with `FONT_PATH=/tmp/marker/...` to avoid a write-permission issue in the system packages directory
- The embedding cluster image does not ship `sentencepiece` or `ai-edge-litert`; `run_embeddings.sh` installs them on demand before starting the build

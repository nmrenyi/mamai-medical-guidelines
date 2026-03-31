# MAMAI Medical Guidelines

These guidelines are used for the RAG system of the [MAMAI project](https://github.com/nmrenyi/mamai).

Raw data shared by Trevor Brokowski, available at [Google Drive](https://drive.google.com/drive/folders/1urBQnXJaay8AlhqQPtcVjWuqZUiFcvOK). Place both data sources under `raw/`.

---

## Repository Structure

```
raw/
  Clinical guidelines_International/      # international guideline PDFs
  Clinical guidelines_Zanzibar-Tanzania/  # Tanzania/Zanzibar guideline PDFs

scripts/
  extract_to_markdown.py   # extract international PDFs → markdown (marker-pdf)
  extract_tanzania.py      # extract Tanzania PDFs → markdown (marker-pdf)
  submit_extraction.sh     # submit international extraction job to LiGHT cluster
  submit_tanzania.sh       # submit Tanzania extraction job to LiGHT cluster
  exclusions.py            # PDFs to skip or deduplicate
  chunk_guidelines.py      # chunk markdowns → chunks_for_rag.txt (uses <!-- page: N --> markers)
  chunk_guidelines_pdf.py  # (deprecated) PyMuPDF-based chunking, bypasses markdown step

processed/
  markdowns/
    international/         # marker-pdf extracted markdowns, one .md per PDF
    tanzania/              # marker-pdf extracted markdowns, Tanzania PDFs
  markdowns_backup/        # backup of markdowns before page-marker regex fix
  chunks_for_rag.txt       # RAG chunks — OUTDATED (from PyMuPDF path, see TODO)
  embeddings.sqlite        # vector embeddings — OUTDATED (from PyMuPDF path, see TODO)
```

---

## Current Workflow

### Step 1 — PDF Extraction (marker-pdf, GPU cluster)

PDFs are converted to markdown using [marker-pdf](https://github.com/VikParuchuri/marker), an ML-based converter that recovers document structure (headings, tables, lists).

Each output `.md` contains `<!-- page: N -->` comments marking physical page boundaries, derived from marker-pdf's `{N}------------------------------------------------` separators (`paginate_output=True`).

**Submit to LiGHT cluster (EPFL) via run:ai:**

```bash
# International guidelines (39 PDFs)
bash scripts/submit_extraction.sh

# Tanzania/Zanzibar guidelines (19 PDFs)
bash scripts/submit_tanzania.sh
```

Monitor with:
```bash
runai logs mamai-extract-intl -f
runai logs mamai-extract-tz -f
```

Pull results after completion:
```bash
rsync -av --include="*.md" --exclude="tanzania/" --exclude="*/" \
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/markdown/" \
  "processed/markdowns/international/"

rsync -av \
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/markdown/tanzania/" \
  "processed/markdowns/tanzania/"
```

> **Cluster note:** `FONT_PATH=/tmp/marker/GoNotoCurrent-Regular.ttf` is set so marker-pdf writes its font to a writable path (the system packages dir is read-only for non-root users). Jobs run as uid=296712 (yiren) for NFS access.

### Step 2 — Chunking (TODO)

Re-run `scripts/chunk_guidelines.py` on the new marker-pdf markdowns to regenerate `processed/chunks_for_rag.txt`.

> `chunks_for_rag.txt` and `embeddings.sqlite` are currently from the **deprecated PyMuPDF path** (`chunk_guidelines_pdf.py`), which does raw text extraction without ML-based structure recovery. They must be regenerated from the marker-pdf markdowns.

### Step 3 — Embedding (TODO)

After chunking, re-run the embedding pipeline to regenerate `processed/embeddings.sqlite` from the new chunks.

---

## Why marker-pdf over PyMuPDF?

| | marker-pdf (current) | PyMuPDF (deprecated) |
|---|---|---|
| Text quality | ML-based: recovers headings, tables, lists | Raw text dump, no structure |
| Tables | Reconstructed as markdown tables | Flattened or garbled |
| Page markers | Accurate `<!-- page: N -->` from PDF boundaries | Accurate but no structure context |
| Speed | Slow (requires GPU) | Fast (CPU only) |
| Output | `processed/markdowns/` | Chunks directly, no intermediate markdown |

---

## Notes

- `exclusions.py` lists PDFs excluded from processing (duplicates, non-English, etc.)
- `extract_tanzania.py --force` re-extracts even if output already exists
- `processed/markdowns_backup/` preserves originals before the page-marker fix (the initial extraction used a wrong separator pattern that inflated page counts)

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
  extract_to_markdown.py   # convert international PDFs → markdown via marker-pdf
  extract_tanzania.py      # convert Tanzania PDFs → markdown via marker-pdf
  submit_extraction.sh     # run international extraction on LiGHT H100 cluster
  submit_tanzania.sh       # run Tanzania extraction on LiGHT H100 cluster
  exclusions.py            # PDFs to skip or deduplicate
  chunk_guidelines.py      # chunk markdowns into RAG passages (reads <!-- page: N --> markers)
  chunk_guidelines_pdf.py  # (deprecated) PyMuPDF direct chunking, no markdown intermediate

processed/                 # gitignored — generated outputs
  markdowns/
    international/         # 39 marker-pdf markdowns, one per PDF
    tanzania/              # 19 marker-pdf markdowns, one per PDF
  chunks_for_rag.txt       # RAG chunks (TODO: regenerate from marker-pdf markdowns)
  embeddings.sqlite        # vector store (TODO: regenerate from marker-pdf chunks)
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
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/markdown/" \
  "processed/markdowns/international/"

rsync -av \
  "light:/mnt/light/scratch/users/yiren/mamai-medical-guidelines/processed/markdown/tanzania/" \
  "processed/markdowns/tanzania/"
```

### Step 2 — Markdown → Chunks (TODO)

Re-run `chunk_guidelines.py` on the marker-pdf markdowns to regenerate `chunks_for_rag.txt`.

`chunks_for_rag.txt` and `embeddings.sqlite` are currently produced by the **deprecated PyMuPDF path** (`chunk_guidelines_pdf.py`), which does raw text extraction without ML-based structure recovery. They need to be regenerated.

### Step 3 — Chunks → Embeddings (TODO)

Re-run the embedding pipeline on the new chunks to regenerate `embeddings.sqlite`.

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

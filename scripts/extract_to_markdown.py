"""
Extract international guideline PDFs to markdown using marker-pdf.

Walks raw/Clinical guidelines_International/Clinical guidelines_with highlights/,
applies exclusions from exclusions.py, and writes one .md per PDF to processed/markdown/.

Usage:
    python scripts/extract_to_markdown.py              # default 3 workers
    python scripts/extract_to_markdown.py --workers 4  # custom worker count
"""

import argparse
import os
import sys
from multiprocessing import Process, Queue
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent))
from exclusions import EXCLUDE, DEDUP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "raw" / "Clinical guidelines_International" / "Clinical guidelines_with highlights"
OUTPUT_DIR = PROJECT_ROOT / "processed" / "markdown"

# marker-pdf's default page separator when paginate_output=True
MARKER_PAGE_SEP = "-" * 48


def get_relative_path(pdf_path: Path) -> str:
    """Get path relative to RAW_DIR (used for exclusion matching)."""
    return str(pdf_path.relative_to(RAW_DIR))


def is_excluded(rel_path: str) -> bool:
    """Check if a file should be skipped based on EXCLUDE and DEDUP lists."""
    for excluded_path, _reason in EXCLUDE:
        if rel_path == excluded_path:
            return True
    if rel_path in DEDUP:
        return True
    return False


def collect_pdfs() -> list[Path]:
    """Collect all PDFs to process, applying exclusions."""
    pdfs = []
    for root, _dirs, files in os.walk(RAW_DIR):
        for f in sorted(files):
            if not f.lower().endswith(".pdf"):
                continue
            full_path = Path(root) / f
            rel_path = get_relative_path(full_path)
            if is_excluded(rel_path):
                print(f"  SKIP: {rel_path}")
                continue
            pdfs.append(full_path)
    return pdfs


def normalize_page_markers(text: str) -> str:
    """Replace marker-pdf's page separators with <!-- page: N --> comments."""
    parts = text.split(MARKER_PAGE_SEP)
    result = []
    for i, part in enumerate(parts):
        page_num = i + 1
        marker = f"<!-- page: {page_num} -->"
        result.append(f"{marker}\n{part.strip()}")
    return "\n\n".join(result)


def worker_fn(worker_id: int, pdf_paths: list[Path], output_dir: Path, progress_queue: Queue):
    """Worker process: loads its own model and processes its share of PDFs."""
    from marker.models import create_model_dict
    from marker.converters.pdf import PdfConverter

    config = {
        "paginate_output": True,
        "extract_images": False,
    }
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict, config=config)

    for pdf_path in pdf_paths:
        stem = pdf_path.stem
        output_path = output_dir / f"{stem}.md"
        try:
            rendered = converter(str(pdf_path))
            markdown = normalize_page_markers(rendered.markdown)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8")
            progress_queue.put(("OK", worker_id, pdf_path.name))
        except Exception as e:
            progress_queue.put(("ERROR", worker_id, f"{pdf_path.name}: {e}"))


def main():
    parser = argparse.ArgumentParser(description="Extract guideline PDFs to markdown")
    parser.add_argument("--workers", type=int, default=3,
                        help="Number of parallel workers (default: 3, ~4GB RAM each)")
    args = parser.parse_args()

    print(f"Source: {RAW_DIR}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Workers: {args.workers}")
    print()

    # Collect PDFs
    print("Collecting PDFs...")
    pdfs = collect_pdfs()
    print(f"Found {len(pdfs)} PDFs to process.\n")

    if not pdfs:
        print("No PDFs found. Check that raw/ is populated.")
        sys.exit(1)

    # Split PDFs across workers (round-robin)
    chunks = [[] for _ in range(args.workers)]
    for i, pdf in enumerate(pdfs):
        chunks[i % args.workers].append(pdf)

    # Launch workers
    print(f"Launching {args.workers} workers...")
    progress_queue = Queue()
    processes = []
    for worker_id, chunk in enumerate(chunks):
        if not chunk:
            continue
        p = Process(target=worker_fn, args=(worker_id, chunk, OUTPUT_DIR, progress_queue))
        p.start()
        processes.append(p)

    # Monitor progress
    done = 0
    errors = 0
    total = len(pdfs)
    while done + errors < total:
        status, worker_id, msg = progress_queue.get()
        if status == "OK":
            done += 1
            print(f"  [{done + errors}/{total}] Worker {worker_id}: {msg}")
        else:
            errors += 1
            print(f"  [{done + errors}/{total}] Worker {worker_id} ERROR: {msg}")

    for p in processes:
        p.join()

    print(f"\nDone. {done} succeeded, {errors} failed. Output in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

"""
Extract new source PDFs to markdown using marker-pdf.

Processes PDFs from raw/open-books/ (and optionally raw/exams/ and
raw/whole-books/), writing one .md per PDF to processed/extracted/international/.
Skips files whose output already exists unless --force is given.

Usage:
    python scripts/extract_new_sources.py              # open-books/ only
    python scripts/extract_new_sources.py --also-exams --also-whole-books
    python scripts/extract_new_sources.py --workers 4
    python scripts/extract_new_sources.py --force      # re-extract even if output exists
"""

import argparse
import re
import sys
from multiprocessing import Process, Queue
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "processed" / "extracted" / "international"

# PDFs rated "Exclude" in source-research/rag-source-evaluation.md — skip by default.
EXCLUDE_STEMS = {
    # open-books — governance/professional framework, not clinical
    "icm-professional-framework-for-midwifery",
    "who-midwifery-education-modules-1",
    # exams — administrative, no clinical content
    "icm-essential-competencies-assessment-guide",
    "nmc-midwifery-blueprint",
    "nmc-midwifery-cbt-booklet",
    "nmc-midwifery-test-specification",
    "amcb-candidate-handbook",
    "who-midwifery-educator-core-competencies",
    # whole-books — encyclopaedic textbooks / bioscience / jurisdiction-specific
    "mayes-midwifery",
    "myles-textbook-for-midwives",
    "midwifery-preparation-for-practice",
    "physiology-in-childbearing",
    "varneys-midwifery",
    "acm-midwifery-consultation-referral-guidelines",
}

_CURLY_PAGE = re.compile(r"^\{(\d+)\}-{48}$", re.MULTILINE)


def normalize_page_markers(text: str) -> str:
    return _CURLY_PAGE.sub(lambda m: f"<!-- page: {int(m.group(1)) + 1} -->", text)


def collect_pdfs(dirs: list[Path], force: bool) -> list[Path]:
    pdfs = []
    for d in dirs:
        if not d.exists():
            print(f"  SKIP dir (not found): {d}")
            continue
        for pdf in sorted(d.glob("*.pdf")):
            if pdf.stem in EXCLUDE_STEMS:
                print(f"  SKIP (excluded): {pdf.name}")
                continue
            out = OUTPUT_DIR / f"{pdf.stem}.md"
            if out.exists() and not force:
                print(f"  SKIP (already extracted): {pdf.name}")
                continue
            pdfs.append(pdf)
    return pdfs


def worker_fn(worker_id: int, pdf_paths: list[Path], output_dir: Path, progress_queue: Queue):
    from marker.models import create_model_dict
    from marker.converters.pdf import PdfConverter

    config = {"paginate_output": True, "extract_images": False}
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict, config=config)

    for pdf_path in pdf_paths:
        output_path = output_dir / f"{pdf_path.stem}.md"
        try:
            rendered = converter(str(pdf_path))
            markdown = normalize_page_markers(rendered.markdown)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8")
            progress_queue.put(("OK", worker_id, pdf_path.name))
        except Exception as e:
            progress_queue.put(("ERROR", worker_id, f"{pdf_path.name}: {e}"))


def main():
    parser = argparse.ArgumentParser(description="Extract new source PDFs to markdown")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="Re-extract even if output exists")
    parser.add_argument("--also-exams", action="store_true", help="Include raw/exams/")
    parser.add_argument("--also-whole-books", action="store_true", help="Include raw/whole-books/")
    args = parser.parse_args()

    dirs = [PROJECT_ROOT / "raw" / "open-books"]
    if args.also_exams:
        dirs.append(PROJECT_ROOT / "raw" / "exams")
    if args.also_whole_books:
        dirs.append(PROJECT_ROOT / "raw" / "whole-books")

    print(f"Output: {OUTPUT_DIR}")
    print(f"Workers: {args.workers}")
    print(f"Dirs: {[str(d) for d in dirs]}")
    print()

    print("Collecting PDFs...")
    pdfs = collect_pdfs(dirs, args.force)
    print(f"\nFound {len(pdfs)} PDFs to extract.\n")

    if not pdfs:
        print("Nothing to do.")
        return

    chunks = [[] for _ in range(args.workers)]
    for i, pdf in enumerate(pdfs):
        chunks[i % args.workers].append(pdf)

    print(f"Launching {args.workers} workers...")
    progress_queue: Queue = Queue()
    processes = []
    for worker_id, chunk in enumerate(chunks):
        if not chunk:
            continue
        p = Process(target=worker_fn, args=(worker_id, chunk, OUTPUT_DIR, progress_queue))
        p.start()
        processes.append(p)

    done = errors = 0
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

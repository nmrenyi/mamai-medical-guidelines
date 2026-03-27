"""
chunk_guidelines_pdf.py — Chunk guidelines directly from PDFs using PyMuPDF.

Unlike chunk_guidelines.py (which reads MMORE markdown with inaccurate page
markers), this script extracts text page-by-page from the original PDFs so
that PAGE:N in each chunk matches the actual physical PDF page number.

Output format is identical to chunk_guidelines.py so embed_parallel.py works
unchanged.

Usage:
    python scripts/chunk_guidelines_pdf.py
    python scripts/chunk_guidelines_pdf.py --chunk-size 800 --overlap 100
    python scripts/chunk_guidelines_pdf.py --output processed/chunks_for_rag.txt
"""

import argparse
import re
from pathlib import Path

import fitz  # PyMuPDF — install with: pip install pymupdf

# ---------------------------------------------------------------------------
# File selection (same lists as chunk_guidelines.py)
# ---------------------------------------------------------------------------

SKIP_FILES = {
    "WHO_ANCExSummary_2016",
    "WHO_PositiveBirthExSum_2018",
    "tanzania-nursing-midwifery-curriculum-level5",  # duplicate of Curr_NTA Level 5_27.07
    "tanzania-nursing-midwifery-curriculum-level6",  # duplicate of Curr_NTA Level 6_27.07 Tanzania
}

HIGH_RELEVANCE = {
    "ACOG_Preconcepcare_2019", "AJGP_Preconception_2024",
    "WHO_ANC_2016", "NICE_Antenatal_2021", "NICE_Nutrition_2025",
    "ACM_FetalMove_2017", "NHS_Fetal_2019",
    "WHO_PositiveBirth_2018", "NICE_intrapartum_2023", "WHO_LabourCare_2020",
    "RCM_InductionLabour_2019", "AJOG_BirthPlan_2023", "WHO_Cord_2014",
    "WHO_Sepsis_2015",
    "NICE_Posnatal_2021", "WHO_PNC_2013",
    "WHO_Neborn_2017", "ERC_NewbornResuscitation_2021",
    "enc-course-overview-09.05.2024",
    "NICE_MentalHealth_2020", "RCM_MentalHealth_2015",
    "WHO_IntegratedPregBirth_2015", "WHO_Complications_2017",
    "ICM_EssentialCompetencies_2024", "ACM_Referral_2021",
}

MIN_CHUNK_CHARS = 80

# ---------------------------------------------------------------------------
# Chunking (identical logic to chunk_guidelines.py)
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    separators = ["\n\n", "\n", ". ", " "]
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break
        break_pos = end
        for sep in separators:
            pos = text.rfind(sep, start + overlap, end)
            if pos != -1:
                break_pos = pos + len(sep)
                break
        chunk = text[start:break_pos].strip()
        if chunk:
            chunks.append(chunk)
        start = max(start + 1, break_pos - overlap)
    return chunks


# ---------------------------------------------------------------------------
# PDF processing
# ---------------------------------------------------------------------------

def process_pdf(pdf_path: Path, chunk_size: int, overlap: int) -> list[str]:
    """Extract text from each physical page and return prefixed chunks."""
    stem = pdf_path.stem
    result: list[str] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"\n  ERROR opening {pdf_path.name}: {e}")
        return result

    for page_idx in range(len(doc)):
        page_num = page_idx + 1  # 1-indexed physical page number
        page = doc[page_idx]
        text = page.get_text()
        if not text or not text.strip():
            continue
        for chunk in chunk_text(text.strip(), chunk_size, overlap):
            if len(chunk) < MIN_CHUNK_CHARS:
                continue
            result.append(f"[SOURCE:{stem}|PAGE:{page_num}]\n{chunk}")

    doc.close()
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Chunk PDFs for RAG using physical page numbers"
    )
    parser.add_argument("--output", default="processed/chunks_for_rag.txt")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--overlap",    type=int, default=100)
    parser.add_argument("--all", action="store_true",
                        help="Include all international files, not just HIGH-relevance")
    args = parser.parse_args()

    project_root  = Path(__file__).resolve().parent.parent
    raw_intl      = project_root / "raw" / "Clinical guidelines_International"
    raw_tanzania  = project_root / "raw" / "Clinical guidelines_Zanzibar-Tanzania"
    output_path   = project_root / args.output

    # Collect all PDFs
    intl_pdfs     = sorted(raw_intl.rglob("*.pdf"))     if raw_intl.exists()     else []
    tanzania_pdfs = sorted(raw_tanzania.rglob("*.pdf")) if raw_tanzania.exists() else []

    to_process: list[Path] = []
    to_skip:    list[tuple[Path, str]] = []

    seen_stems: set[str] = set()

    for pdf in intl_pdfs:
        stem = pdf.stem
        if stem in seen_stems:
            continue  # deduplicate (same file in multiple subfolders)
        seen_stems.add(stem)
        if stem in SKIP_FILES:
            to_skip.append((pdf, "duplicate"))
        elif not args.all and stem not in HIGH_RELEVANCE:
            to_skip.append((pdf, "not HIGH"))
        else:
            to_process.append(pdf)

    for pdf in tanzania_pdfs:
        stem = pdf.stem
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        if stem in SKIP_FILES:
            to_skip.append((pdf, "duplicate"))
        else:
            to_process.append(pdf)

    if not to_process:
        print("No PDFs to process.")
        return

    total = len(to_process)
    all_chunks: list[str] = []

    for i, pdf_path in enumerate(to_process, start=1):
        print(f"  [{i:>2}/{total}] {pdf_path.name:<50}", end="", flush=True)
        chunks = process_pdf(pdf_path, args.chunk_size, args.overlap)
        all_chunks.extend(chunks)
        print(f"  {len(chunks):>4} chunks")

    if to_skip:
        print(f"\nSkipped ({len(to_skip)} files):")
        for pdf_path, reason in to_skip:
            print(f"  {reason:<12}  {pdf_path.name}")

    if not all_chunks:
        print("\nNo chunks produced.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            lines = chunk.split("\n", 1)
            metadata = lines[0]
            body = lines[1] if len(lines) > 1 else ""
            f.write(f"<sep>{metadata}\n{body}\n")

    total_chars = sum(
        len(c.split("\n", 1)[1]) if "\n" in c else len(c) for c in all_chunks
    )
    print(f"\nOutput:          {output_path}")
    print(f"Total chunks:    {len(all_chunks)}")
    print(f"Avg chunk size:  {total_chars // len(all_chunks)} chars")
    print(f"Output size:     {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

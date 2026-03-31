"""
Exclusion and deduplication rules for the RAG extraction pipeline.

These files exist in raw/ but should be skipped or deduplicated during processing.
raw/ is kept as a faithful mirror of the Google Drive source — all filtering
happens here in code so decisions are tracked, reviewable, and reversible.
"""

# Files to skip entirely during extraction.
# Each entry: (relative path from the guidelines root, reason)
EXCLUDE = [
    (
        "Competency 5 PostNatal/WHO_PostnatalEsp_2022.pdf",
        "Spanish-language duplicate of WHO postnatal guidelines"
    ),
    (
        "The State of the World_s Midwifery 2021 _ United Nations Population Fund.html",
        "Saved webpage (HTML), not a clinical guideline PDF"
    ),
    (
        "The Zanzibar Nurses and Midwifery Council.docx",
        "Word document (.docx), not a PDF — marker-pdf cannot process it"
    ),
]

# Duplicate files: maps the copy to skip -> the canonical copy to keep.
# Both paths are relative to the guidelines root.
DEDUP = {
    "Competency 4 Birth/WHO_Complications_2017.pdf": "WHO_Complications_2017.pdf",
}

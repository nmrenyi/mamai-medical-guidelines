"""
embed_parallel.py — Run build_embeddings.py in N parallel subprocesses.

Each worker is an independent OS process with its own TFLite interpreter,
limited to (total_cores // workers) threads so cores are shared fairly.
Workers write their own SQLite parts; this script merges them at the end.

Live display shows one progress row per worker, updated every 2 seconds.

Usage:
    python scripts/embed_parallel.py --workers 3
    python scripts/embed_parallel.py \\
        --workers   3 \\
        --gecko     /path/to/Gecko_1024_quant.tflite \\
        --tokenizer /path/to/sentencepiece.model \\
        --output    processed/embeddings.sqlite
"""

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT  = SCRIPT_DIR.parent
MAMAI_DIR     = PROJECT_ROOT / "../../mamai/app/model_backup"
BUILD_SCRIPT  = str(SCRIPT_DIR / "build_embeddings.py")

DEFAULT_CHUNKS    = str(PROJECT_ROOT / "processed/chunks_for_rag.txt")
DEFAULT_GECKO     = str(MAMAI_DIR / "Gecko_1024_quant.tflite")
DEFAULT_TOKENIZER = str(MAMAI_DIR / "sentencepiece.model")
DEFAULT_OUTPUT    = str(PROJECT_ROOT / "processed/embeddings.sqlite")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count_chunks(chunks_path: str) -> int:
    """Count <sep> separators = number of chunks in the file."""
    count = 0
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("<sep>"):
                count += 1
    return count


def parse_progress_from_log(log_path: Path) -> tuple[int, int, str]:
    """
    Read the last progress line from a worker log file.
    Returns (done, total, eta_str).
    Progress lines look like:
      \r[████░░] 1234/ 2928  42.2%  elapsed 03:12  eta 04:22  SOURCE:...|PAGE:N
    """
    if not log_path.exists():
        return 0, 0, "--:--"
    try:
        raw = log_path.read_bytes()
    except OSError:
        return 0, 0, "--:--"

    # Split on \r and \n, take last non-empty chunk
    parts = re.split(rb"[\r\n]+", raw)
    last = b""
    for p in reversed(parts):
        if p.strip():
            last = p
            break

    text = last.decode("utf-8", errors="replace")

    m_counts = re.search(r"\]\s*(\d+)\s*/\s*(\d+)", text)
    m_eta    = re.search(r"eta\s+(\S+)", text)
    m_label  = re.search(r"eta\s+\S+\s+(.*)", text)

    done  = int(m_counts.group(1)) if m_counts else 0
    total = int(m_counts.group(2)) if m_counts else 0
    eta   = m_eta.group(1)         if m_eta    else "--:--"
    label = m_label.group(1).strip()[:40] if m_label else ""

    return done, total, eta, label  # type: ignore[return-value]


def _fmt_bar(done: int, total: int, width: int = 20) -> str:
    if total == 0:
        return "░" * width
    filled = int(width * done / total)
    return "█" * filled + "░" * (width - filled)


def _fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parallel embedding coordinator")
    parser.add_argument("--chunks",    default=DEFAULT_CHUNKS)
    parser.add_argument("--gecko",     default=DEFAULT_GECKO)
    parser.add_argument("--tokenizer", default=DEFAULT_TOKENIZER)
    parser.add_argument("--output",    default=DEFAULT_OUTPUT)
    parser.add_argument("--workers",   type=int, default=3,
                        help="Number of parallel subprocesses (default: 3)")
    args = parser.parse_args()

    for label, path in [("chunks", args.chunks), ("gecko", args.gecko),
                        ("tokenizer", args.tokenizer)]:
        if not Path(path).exists():
            sys.exit(f"ERROR: {label} file not found: {path}")

    workers = max(1, args.workers)

    # Threads per worker: give each worker a fair share but at least 1
    cpu_count  = os.cpu_count() or 4
    thr_per_w  = max(1, cpu_count // workers)

    print(f"Chunks:         {args.chunks}")
    print(f"Gecko:          {args.gecko}")
    print(f"Tokenizer:      {args.tokenizer}")
    print(f"Output:         {args.output}")
    print(f"Workers:        {workers}")
    print(f"Threads/worker: {thr_per_w}  (of {cpu_count} logical cores)")
    print()

    # Count total chunks
    print("Counting chunks... ", end="", flush=True)
    total = count_chunks(args.chunks)
    print(f"{total} chunks.")

    if total == 0:
        sys.exit("ERROR: no chunks found.")

    # Compute slices
    batch = (total + workers - 1) // workers
    slices = [(w, w * batch, min((w + 1) * batch, total)) for w in range(workers)]

    # Temp directory for part files and logs
    tmp_dir = Path(tempfile.mkdtemp(prefix="gecko_par_"))
    print(f"Temp dir:       {tmp_dir}\n")

    # Launch subprocesses
    procs: list[tuple[int, subprocess.Popen, Path, str, int, int]] = []
    for w, start, end in slices:
        log_path = tmp_dir / f"worker_{w}.log"
        part_db  = str(tmp_dir / f"part_{w:03d}.sqlite")
        cmd = [
            sys.executable, BUILD_SCRIPT,
            "--chunks",      args.chunks,
            "--gecko",       args.gecko,
            "--tokenizer",   args.tokenizer,
            "--output",      part_db,
            "--start-chunk", str(start),
            "--end-chunk",   str(end),
            "--num-threads", str(thr_per_w),
        ]
        log_file = open(log_path, "wb")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
        procs.append((w, proc, log_path, part_db, start, end))
        print(f"  Worker {w}: PID {proc.pid}  chunks [{start}:{end}]  log → {log_path.name}")

    print(f"\nAll {workers} workers started. Monitoring...\n")

    # Reserve N+2 blank lines for the live display
    for _ in range(workers + 2):
        print()

    start_time = time.time()

    # Live progress loop
    while True:
        alive = [p for _, p, _, _, _, _ in procs if p.poll() is None]

        # Move cursor up to overwrite the status block
        print(f"\033[{workers + 2}A", end="", flush=True)

        done_total = 0
        for w, proc, log_path, _, w_start, w_end in procs:
            w_total = w_end - w_start
            result  = parse_progress_from_log(log_path)
            # parse_progress_from_log returns 4 values
            if len(result) == 4:
                done, _, eta, label = result
            else:
                done, _, eta = result
                label = ""

            done_total += done
            bar    = _fmt_bar(done, w_total)
            pct    = f"{done / w_total * 100:5.1f}%" if w_total else "  0.0%"
            status = "✓ done  " if proc.poll() == 0 else ("✗ error " if proc.poll() else "running ")
            print(f"  W{w} [{bar}] {done:>5}/{w_total}  {pct}  eta {eta:<8}  {status}  {label:<35}")

        elapsed = time.time() - start_time
        rate    = done_total / elapsed if elapsed > 0 else 0
        eta_all = _fmt_time((total - done_total) / rate) if rate > 0 else "--:--"
        print(f"\n  Total: {done_total:>6}/{total}  elapsed {_fmt_time(elapsed)}  eta {eta_all}  "
              f"({len(alive)}/{workers} workers active)          ")
        print()

        if not alive:
            break
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"\nAll workers finished in {_fmt_time(elapsed)}.")

    # Check for failures
    failed = [(w, p.returncode) for w, p, _, _, _, _ in procs if p.returncode != 0]
    if failed:
        print(f"WARNING: {len(failed)} worker(s) failed: {failed}")
        print("         Check logs in", tmp_dir)

    # Merge part SQLites into final output in original chunk order
    print(f"\nMerging {workers} part files → {args.output} ...", end=" ", flush=True)
    out_path = Path(args.output)
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute(
        """
        CREATE TABLE rag_vector_store (
            ROWID      INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            text       TEXT    NOT NULL,
            embeddings REAL    NOT NULL
        )
        """
    )
    cur = conn.cursor()
    total_inserted = 0
    for w, _, _, part_db, _, _ in procs:
        part_path = Path(part_db)
        if not part_path.exists():
            print(f"\n  WARNING: part_{w:03d}.sqlite missing — skipping")
            continue
        src = sqlite3.connect(str(part_path))
        rows = src.execute("SELECT text, embeddings FROM rag_vector_store ORDER BY ROWID").fetchall()
        cur.executemany(
            "INSERT INTO rag_vector_store (text, embeddings) VALUES (?, ?)", rows
        )
        src.close()
        total_inserted += len(rows)

    conn.commit()
    conn.close()
    print(f"done. {total_inserted} rows written.")

    out_size = out_path.stat().st_size / (1024 * 1024)
    print(f"\nOutput: {args.output}  ({out_size:.1f} MB)")
    print(f"Skipped (embed errors): {total - total_inserted}")

    if not failed:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        print(f"Logs preserved in: {tmp_dir}")

    print(
        "\nNext steps:"
        "\n  adb push processed/embeddings.sqlite"
        " /sdcard/Android/data/com.example.app/files/embeddings.sqlite"
    )


if __name__ == "__main__":
    main()

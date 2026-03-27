"""
build_embeddings.py — Embed chunked guidelines and write embeddings.sqlite

Reads processed/chunks_for_rag.txt (produced by chunk_guidelines.py),
embeds each chunk using the Gecko TFLite model, and writes a SQLite
database in the exact format expected by Android's SqliteVectorStore
(Google AI Edge localagents-rag library):

  Table: rag_vector_store (ROWID, text TEXT, embeddings REAL)
  Embedding blob: b'VF32' + 768 × float32 little-endian = 3076 bytes

Usage:
    python scripts/build_embeddings.py
    python scripts/build_embeddings.py --chunks processed/chunks_for_rag.txt
    python scripts/build_embeddings.py \\
        --gecko     ../../mamai/app/model_backup/Gecko_1024_quant.tflite \\
        --tokenizer ../../mamai/app/model_backup/sentencepiece.model \\
        --output    processed/embeddings.sqlite \\
        --workers   8
"""

import argparse
import multiprocessing as mp
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Defaults — paths relative to the project root
# ---------------------------------------------------------------------------

PROJECT_ROOT     = Path(__file__).resolve().parent.parent
MAMAI_MODEL_DIR  = PROJECT_ROOT / "../../mamai/app/model_backup"

DEFAULT_CHUNKS     = str(PROJECT_ROOT / "processed/chunks_for_rag.txt")
DEFAULT_GECKO      = str(MAMAI_MODEL_DIR / "Gecko_1024_quant.tflite")
DEFAULT_TOKENIZER  = str(MAMAI_MODEL_DIR / "sentencepiece.model")
DEFAULT_OUTPUT     = str(PROJECT_ROOT / "processed/embeddings.sqlite")

BATCH_COMMIT_SIZE = 100

# Magic bytes that prefix every embedding blob in the Android SQLite store.
# Confirmed by inspecting the existing embeddings.sqlite produced on-device.
VF32_MAGIC = b"VF32"


# ---------------------------------------------------------------------------
# Gecko embedder
# ---------------------------------------------------------------------------

class GeckoEmbedder:
    """Wraps the Gecko TFLite model + SentencePiece tokenizer."""

    def __init__(self, gecko_path: str, tokenizer_path: str, num_threads: int = 2):
        import sentencepiece as spm
        try:
            from ai_edge_litert.interpreter import Interpreter, InterpreterOptions
            opts = InterpreterOptions()
            opts.num_threads = num_threads
            self._interpreter = Interpreter(model_path=gecko_path, experimental_op_resolver_type=None)
        except Exception:
            try:
                from ai_edge_litert.interpreter import Interpreter
                self._interpreter = Interpreter(model_path=gecko_path)
            except ImportError:
                try:
                    import tensorflow as tf
                    self._interpreter = tf.lite.Interpreter(
                        model_path=gecko_path, num_threads=num_threads
                    )
                except ImportError:
                    try:
                        import tflite_runtime.interpreter as tflite
                        self._interpreter = tflite.Interpreter(
                            model_path=gecko_path, num_threads=num_threads
                        )
                    except ImportError:
                        sys.exit(
                            "ERROR: install ai-edge-litert, tensorflow, or tflite-runtime.\n"
                            "  pip install ai-edge-litert"
                        )

        self._interpreter.allocate_tensors()
        self._input  = self._interpreter.get_input_details()
        self._output = self._interpreter.get_output_details()
        self._max_len = int(self._input[0]["shape"][1])

        self._sp = spm.SentencePieceProcessor()
        self._sp.load(tokenizer_path)

    def embed(self, text: str) -> list[float]:
        """Return a 768-dim float list for the given text."""
        ids = self._sp.encode_as_ids(text)
        if len(ids) > self._max_len:
            ids = ids[:self._max_len]
        else:
            ids += [0] * (self._max_len - len(ids))

        tokens = np.array([ids], dtype=np.int32)
        self._interpreter.set_tensor(self._input[0]["index"], tokens)
        self._interpreter.invoke()
        vec = self._interpreter.get_tensor(self._output[0]["index"])
        return vec.flatten().tolist()

    @property
    def dim(self) -> int:
        return int(np.prod(self._output[0]["shape"][1:]))


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def init_db(path: str) -> sqlite3.Connection:
    """Create (or overwrite) the SQLite database with the correct schema."""
    db_path = Path(path)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(path)
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
    conn.commit()
    return conn


def pack_embedding(floats: list[float]) -> bytes:
    """Pack a float list as VF32 magic + 768 × float32 little-endian."""
    return VF32_MAGIC + struct.pack(f"<{len(floats)}f", *floats)


# ---------------------------------------------------------------------------
# Chunk file parser
# ---------------------------------------------------------------------------

def parse_chunks(chunks_path: str) -> list[str]:
    """
    Parse the <sep>-delimited file produced by chunk_guidelines.py.

    Each entry starts with a line of the form:
        <sep>[SOURCE:stem|PAGE:N]
    followed by the chunk body on subsequent lines.

    The returned strings include the [SOURCE|PAGE] prefix — that is what
    gets stored in SQLite and embedded (matching Android's memorizeChunks).
    """
    chunks: list[str] = []
    buf: list[str] = []

    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("<sep>"):
                if buf:
                    chunks.append("\n".join(buf).strip())
                after_sep = line[len("<sep>"):]
                buf = [after_sep] if after_sep else []
            else:
                buf.append(line)

    if buf:
        chunks.append("\n".join(buf).strip())

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

def _fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def print_progress(i: int, total: int, start: float, suffix: str = ""):
    """Overwrite the current terminal line with a progress bar + ETA."""
    elapsed = time.time() - start
    frac    = i / total
    filled  = int(30 * frac)
    bar     = "█" * filled + "░" * (30 - filled)
    pct     = f"{frac * 100:5.1f}%"
    eta_str = _fmt_time((elapsed / i) * (total - i)) if i else "--:--"
    line = (
        f"\r[{bar}] {i:>5}/{total}  {pct}"
        f"  elapsed {_fmt_time(elapsed)}  eta {eta_str}"
        f"  {suffix}"
    )
    print(line, end="", flush=True)


# ---------------------------------------------------------------------------
# Parallel worker (must be module-level for multiprocessing spawn)
# ---------------------------------------------------------------------------

def _embed_worker(args: tuple) -> str:
    """
    Embed a slice of chunks and write results to a temporary SQLite file.

    args = (chunks, gecko_path, tokenizer_path, tmp_db_path, progress_path)

    Writes the count of completed chunks to progress_path after every
    BATCH_COMMIT_SIZE rows so the main process can show a live bar.
    Returns tmp_db_path on success.
    """
    chunks, gecko_path, tokenizer_path, tmp_db_path, progress_path = args

    embedder = GeckoEmbedder(gecko_path, tokenizer_path)

    conn = sqlite3.connect(tmp_db_path)
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute(
        "CREATE TABLE part (seq INTEGER PRIMARY KEY, text TEXT, blob BLOB)"
    )
    cur = conn.cursor()

    done = 0
    for seq, text in enumerate(chunks):
        try:
            floats = embedder.embed(text)
            blob   = pack_embedding(floats)
            cur.execute("INSERT INTO part VALUES (?, ?, ?)", (seq, text, blob))
            done += 1
        except Exception:
            pass  # skip; gap in seq is harmless after merge

        if (seq + 1) % BATCH_COMMIT_SIZE == 0:
            conn.commit()
            Path(progress_path).write_text(str(done))

    conn.commit()
    conn.close()
    Path(progress_path).write_text(str(done))
    return tmp_db_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build embeddings.sqlite from chunks")
    parser.add_argument("--chunks",      default=DEFAULT_CHUNKS,    help="Input chunks file")
    parser.add_argument("--gecko",       default=DEFAULT_GECKO,     help="Gecko TFLite model path")
    parser.add_argument("--tokenizer",   default=DEFAULT_TOKENIZER, help="SentencePiece model path")
    parser.add_argument("--output",      default=DEFAULT_OUTPUT,    help="Output SQLite path")
    parser.add_argument("--start-chunk", type=int, default=0,       help="First chunk index (inclusive)")
    parser.add_argument("--end-chunk",   type=int, default=-1,      help="Last chunk index (exclusive); -1 = all")
    parser.add_argument("--num-threads", type=int, default=2,       help="TFLite inference threads per process")
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Parallel worker processes (default: 1; use embed_parallel.py for parallel runs)",
    )
    args = parser.parse_args()

    # Validate inputs
    for label, path in [
        ("chunks",    args.chunks),
        ("gecko",     args.gecko),
        ("tokenizer", args.tokenizer),
    ]:
        if not Path(path).exists():
            sys.exit(f"ERROR: {label} file not found: {path}")

    workers = max(1, args.workers)

    print(f"Chunks:     {args.chunks}")
    print(f"Gecko:      {args.gecko}")
    print(f"Tokenizer:  {args.tokenizer}")
    print(f"Output:     {args.output}")
    print(f"Workers:    {workers}")
    print()

    # Parse chunks
    print("Parsing chunks file...", end=" ", flush=True)
    chunks = parse_chunks(args.chunks)
    print(f"{len(chunks)} chunks found.")

    if not chunks:
        sys.exit("ERROR: no chunks parsed — check chunks file.")

    # Apply chunk slice (used by embed_parallel.py to run a subset)
    if args.start_chunk > 0 or args.end_chunk != -1:
        end = args.end_chunk if args.end_chunk != -1 else len(chunks)
        chunks = chunks[args.start_chunk:end]
        print(f"Processing slice [{args.start_chunk}:{end}] → {len(chunks)} chunks")

    # -----------------------------------------------------------------------
    # Single-worker path (original behaviour)
    # -----------------------------------------------------------------------
    if workers == 1:
        print("Loading Gecko model...", end=" ", flush=True)
        t0 = time.time()
        embedder = GeckoEmbedder(args.gecko, args.tokenizer, num_threads=args.num_threads)
        print(f"done ({time.time() - t0:.1f}s).  Embedding dim: {embedder.dim}  threads: {args.num_threads}")

        conn   = init_db(args.output)
        cursor = conn.cursor()

        print(f"\nEmbedding {len(chunks)} chunks — this will take a while on CPU.\n")
        start  = time.time()
        errors = 0

        for i, text in enumerate(chunks, start=1):
            label = ""
            if text.startswith("[SOURCE:"):
                end = text.find("]")
                if end != -1:
                    label = text[1:end]
            print_progress(i - 1, len(chunks), start, label)

            try:
                floats = embedder.embed(text)
                blob   = pack_embedding(floats)
                cursor.execute(
                    "INSERT INTO rag_vector_store (text, embeddings) VALUES (?, ?)",
                    (text, blob),
                )
            except Exception as e:
                errors += 1
                print(f"\n  WARNING: failed to embed chunk {i}: {e}")

            if i % BATCH_COMMIT_SIZE == 0:
                conn.commit()

        conn.commit()
        conn.close()

    # -----------------------------------------------------------------------
    # Multi-worker path
    # -----------------------------------------------------------------------
    else:
        print(f"Splitting {len(chunks)} chunks across {workers} workers…")
        batch_size = (len(chunks) + workers - 1) // workers
        batches    = [chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)]

        tmp_dir = Path(tempfile.mkdtemp(prefix="gecko_embed_"))
        worker_args = [
            (
                batch,
                args.gecko,
                args.tokenizer,
                str(tmp_dir / f"part_{w:03d}.sqlite"),
                str(tmp_dir / f"progress_{w:03d}.txt"),
            )
            for w, batch in enumerate(batches)
        ]

        print(f"Spawning {len(batches)} worker processes…\n")
        start = time.time()

        ctx    = mp.get_context("spawn")
        pool   = ctx.Pool(workers)
        result = pool.map_async(_embed_worker, worker_args)
        pool.close()

        # Live progress bar — aggregate counts from per-worker progress files
        while not result.ready():
            done = 0
            for *_, progress_path in worker_args:
                p = Path(progress_path)
                if p.exists():
                    try:
                        done += int(p.read_text().strip() or 0)
                    except ValueError:
                        pass
            print_progress(done, len(chunks), start, f"{workers} workers")
            time.sleep(1)

        pool.join()
        tmp_paths = result.get()  # raises if any worker raised

        # Final tally from progress files
        total_done = sum(
            int(Path(p).read_text().strip() or 0)
            for *_, p in worker_args
            if Path(p).exists()
        )
        print_progress(total_done, len(chunks), start, "merging…")

        # Merge part files into final output (preserve original chunk order)
        conn   = init_db(args.output)
        cursor = conn.cursor()
        errors = len(chunks) - total_done

        for tmp_path in tmp_paths:
            src = sqlite3.connect(tmp_path)
            for row in src.execute("SELECT text, blob FROM part ORDER BY seq"):
                cursor.execute(
                    "INSERT INTO rag_vector_store (text, embeddings) VALUES (?, ?)", row
                )
            src.close()

        conn.commit()
        conn.close()

        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    elapsed  = time.time() - start
    out_size = Path(args.output).stat().st_size / (1024 * 1024)

    print_progress(len(chunks), len(chunks), start, "done")
    print()
    print(f"\nDone in {_fmt_time(elapsed)}.")
    print(f"  Chunks embedded: {len(chunks) - errors}/{len(chunks)}")
    print(f"  Output size:     {out_size:.1f} MB")
    print(f"  Output:          {args.output}")
    if errors:
        print(f"  Errors:          {errors}  (those chunks were skipped)")
    print(
        "\nNext steps:"
        "\n  adb push processed/embeddings.sqlite"
        " /sdcard/Android/data/com.example.app/files/embeddings.sqlite"
    )


if __name__ == "__main__":
    main()

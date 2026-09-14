# RAG evaluation — measurements

Scope: this eval focuses on **measurement** retrieval only. Documents and the
newer chatbot tools (medication / document tools) are intentionally out of scope.

Two layers, with different data needs.

## Layer 1 — bug-level unit tests (no data, no PHI, runs anywhere)

Hermetic tests that pin down concrete defects on the measurement retrieval path
and guard the fixes. They stub the heavy runtime deps, so they run on a plain dev
machine.

```bash
cd src/FreeScribe.client
python -m pytest tests/rag -q
```

What they cover:

| File | Target | What it checks |
|------|--------|----------------|
| `test_vectordb_sql.py` | `VectorSearch.py` `VectorDB.search` | patient/date filters render; **xfail:** `date_delta` is ignored — `measurement_search` defaults to `delta=3` but only an exact-match date is emitted; filter values are string-formatted (injectable) |
| `test_reranking.py` | `VectorSearch.py` reranking | **xfail:** `date_rank` returns the unsorted list; log-normalize breaks on negative cross-encoder scores. *Needs real numpy — auto-skips where absent.* |
| `test_metrics.py` | `eval/metrics.py` | the metric math itself |

`xfail(strict=True)` means each known bug is recorded as an *expected failure*.
When you fix a bug the test unexpectedly passes and the suite goes red — that's
your cue to delete the `xfail` marker so it becomes a normal regression test.

> Note: the document OCR **chunker** is not exercised here — measurements are not
> chunked (each is embedded as a single chunk), so the chunker is a document-only
> concern and outside this measurements scope.

## Layer 2 — retrieval-quality eval (needs the runtime + a labeled gold set)

Measures how good measurement retrieval actually is (recall / precision / MRR /
nDCG) against hand-labeled cases. Runs on the clinic/server machine because it
needs numpy, psycopg2, sentence-transformers, the populated pgvector DB, and the
models. It reads only the Postgres vector DB — **no Oscar EMR / SSH needed**.

### 1. Build a gold set

Copy the template and fill in real cases:

```bash
cp chatbot/RAG/eval/gold_set.example.yaml chatbot/RAG/eval/gold_set.yaml
```

Each case maps a query (+ patient, optional date) to the `measurement_ids` that
*should* come back. Aim for ~20–30 cases across measurement types and phrasings.
See the comments in the template for the schema.

> ⚠️ A real gold set is PHI. Keep `gold_set.yaml` and any `*_report.json` out of
> git (already covered by `.gitignore`) and only inside the controlled
> environment.

### 2. Run it

```bash
cd src/FreeScribe.client
python -m chatbot.RAG.eval.run_eval \
    --config /path/to/config.yaml \
    --gold   chatbot/RAG/eval/gold_set.yaml \
    --top-k 10 --rerank --out eval_report.json
```

`--config` is your existing `config.yaml` (it just reads the `VectorDB`
section). `--rerank` additionally scores the MedCPT cross-encoder pass so you can
see how much reranking helps over raw vector search.

### 3. Read the output

A summary table prints to stdout and the full per-case breakdown goes to the
`--out` JSON. Use it to (a) get a baseline number for "how good is measurement
retrieval", and (b) re-run after fixing the Layer-1 bugs to confirm the numbers
move.

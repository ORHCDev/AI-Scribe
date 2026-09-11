# Builds/refreshes Tools/tool_embeddings.jsonl (the tool-discovery index); run after any tool add/remove/rename/description change. Incremental by default; --force rebuilds all.

import sys
from pathlib import Path

# Put src/FreeScribe.client on sys.path so the `chatbot` package resolves regardless of cwd (tool modules import via `from chatbot.Tools...`).
_CLIENT_DIR = Path(__file__).resolve().parent.parent
if str(_CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENT_DIR))

import chatbot.Tools  # noqa: E402,F401 -- importing the package registers every tool
from chatbot.Tools.Tool import TOOL_REGISTRY  # noqa: E402

import argparse  # noqa: E402
import json  # noqa: E402
import numpy as np  # noqa: E402
from typing import Any, Dict, Iterable  # noqa: E402


DEFAULT_PATH = Path(__file__).resolve().parent / "Tools" / "tool_embeddings.jsonl"
MODEL_NAME = "abhinand/MedEmbed-base-v0.1"


def _to_list(embedding: Iterable[float] | np.ndarray) -> list[float]:
    return embedding.tolist() if isinstance(embedding, np.ndarray) else list(embedding)


def write_tool_embedding_jsonl(
    path: str | Path,
    *,
    tool_name: str,
    description: str,
    embedding: Iterable[float] | np.ndarray,
    metadata: Dict[str, Any] | None = None,
) -> None:
    # Append a single tool embedding + metadata as one JSONL record.
    record = {
        "tool_name": tool_name,
        "description": description,
        "embedding": _to_list(embedding),
        "metadata": metadata or {},
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


def clear_jsonl(path: str | Path):
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        f.write("")


def _load_existing(path: Path) -> dict[str, dict]:
    # Load existing embedding records keyed by tool_name.
    existing: dict[str, dict] = {}
    if not path.exists():
        return existing
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            existing[record["tool_name"]] = record
    return existing


def build_index(path: str | Path = DEFAULT_PATH, force: bool = False) -> None:
    # Rewrite the index to match the registry: reuse unchanged embeddings (unless force), embed new/changed, drop orphans.
    path = Path(path)
    existing = {} if force else _load_existing(path)

    records: list[dict] = []
    to_embed: list[tuple] = []

    for tool in TOOL_REGISTRY.values():
        metadata = {"params": tool.parameters}
        prev = existing.get(tool.name)
        if prev is not None and prev.get("description") == tool.description:
            # Unchanged -> reuse stored embedding, refresh metadata.
            records.append(
                {
                    "tool_name": tool.name,
                    "description": tool.description,
                    "embedding": prev["embedding"],
                    "metadata": metadata,
                }
            )
        else:
            records.append(
                {
                    "tool_name": tool.name,
                    "description": tool.description,
                    "embedding": None,
                    "metadata": metadata,
                }
            )
            to_embed.append((tool.name, tool.description, len(records) - 1))

    orphans = sorted(set(existing) - set(TOOL_REGISTRY))
    if orphans:
        print(f"Dropping {len(orphans)} orphaned embedding(s): {', '.join(orphans)}")

    if not to_embed:
        print(f"Index already up to date ({len(records)} tools). Nothing to embed.")
    else:
        print(f"Embedding {len(to_embed)} new/changed tool(s)...")
        # Only pay the model-load cost when there is work to do.
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(MODEL_NAME)
        for name, description, idx in to_embed:
            embedding = model.encode(description, normalize_embeddings=True)
            records[idx]["embedding"] = _to_list(embedding)
            print(f"  embedded {name}")

    # Atomic-ish rewrite: build the full file, then replace.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")
    tmp.replace(path)
    print(f"Wrote {len(records)} tool embeddings to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the chatbot tool embedding index.")
    parser.add_argument("--force", action="store_true", help="Re-embed every tool instead of only new/changed ones.")
    parser.add_argument("--path", default=str(DEFAULT_PATH), help=f"Output JSONL path (default: {DEFAULT_PATH}).")
    args = parser.parse_args()
    build_index(path=args.path, force=args.force)

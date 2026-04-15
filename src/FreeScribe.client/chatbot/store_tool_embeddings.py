from Tools.Tool import TOOL_REGISTRY
from sentence_transformers import SentenceTransformer

import json
import numpy as np
from pathlib import Path
from typing import Any, Dict, Iterable

import time

def write_tool_embedding_jsonl(
    path: str | Path,
    *,
    tool_name: str,
    description: str,
    embedding: Iterable[float] | np.ndarray,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """
    Append a single tool embedding + metadata as one JSONL record.
    """

    record = {
        "tool_name": tool_name,
        "description": description,
        "embedding": (
            embedding.tolist()
            if isinstance(embedding, np.ndarray)
            else list(embedding)
        ),
        "metadata": metadata or {},
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


def clear_jsonl(path : str | Path):
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        f.write("")



model = SentenceTransformer("abhinand/MedEmbed-base-v0.1")

path = r".\Tools\tool_embeddings.jsonl"

clear_jsonl(path)

for i, tool in enumerate(TOOL_REGISTRY.values()):

    # Store tool metadata
    metadata = {
        "params" : tool.parameters,
    }
    # Create embedding
    embedding = model.encode(tool.description, normalize_embeddings=True)
    
    # Write to JSONL 
    write_tool_embedding_jsonl(
        path,
        tool_name=tool.name,
        description=tool.description,
        embedding=embedding,
        metadata=metadata
    )

    print(f"Embedded tool {tool.name}")
    time.sleep(10)
        


     
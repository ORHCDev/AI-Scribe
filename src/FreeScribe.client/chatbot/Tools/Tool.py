from dataclasses import dataclass
from typing import Callable, Dict, Any, List
import pandas as pd

import json
import numpy as np

@dataclass
class Tool:
    name: str
    category: str
    description: str
    context: str
    parameters: Dict[str, str]
    func: Callable[..., Any]


    def call(self, **kwargs):
        return self.func(**kwargs)
    
    def get_str(self):
        """
        Returns string representation of Tool.
        """
        params = ", ".join(f"{k}: {v}" for k, v in self.parameters.items())
        return (
            f"Tool(name='{self.name}', "
            f"category='{self.category}', "
            f"params=[{params}], "
            f"description='{self.description}')"
        )
    
    def __str__(self):
        """
        Custom print for Tool object.
        """
        return self.get_str()


    def __repr__(self):
        return (
            f"Tool("
            f"name={self.name!r}, "
            f"category={self.category!r}, "
            f"parameters={self.parameters!r}, "
            f"func={self.func.__name__}"
            f")"
        )


class ToolRegistry:
    """
    Registry that expects a tool dictionary for easy execution of Tools.
    """
    def __init__(self, tools: dict[str, Tool]):
        self.tools = tools

    def get(self, name: str) -> Tool:
        return self.tools[name]

    def list(self):
        return list(self.tools.values())
    
    def keys(self):
        return self.tools.keys()

    def execute_tool(self, name: str, **args):
        return self.get(name).call(**args)
    


@dataclass
class ToolReturn:
    """
    Dataclass that is returned by Tool functions

    Attributes
    ----------
    label : str
        String that labels the results (i.e. "Demographic Information").

    send_to_ai : bool
        If True, will tell program to send the query results back to AI .

    query_results : list[dict[str, str | int]] | str
        The queried results.

    save_results : list[dict[str, str | int]] | str
        The results to save (Often trimmed query_results).    
    """

    label: str
    send_to_ai: bool
    query_results: list[dict[str, str | int]] | str
    save_results: list[dict[str, str | int]] | str
    
    def results_to_text(self, choice="query") -> str:
        """
        Takes query or save results and converts it to a string that has a tabular format.
        Expects selected results to be in list[dict] format.
        """
        

        # Convert list[dict] to Dataframe for tabular string format
        if choice == "query":
            results = self.query_results
        else:
            results = self.save_results

        if type(results) == str:
            return results
        else:
            df = pd.DataFrame(results)
            return df.to_string(index=False, na_rep="")




TOOL_REGISTRY: dict[str, Tool] = {}


def tool(
    *,
    name: str | None = None,
    category: str,
    description: str,
    context: str = "",
    parameters: dict[str, str]
):
    """
    Decorator to create a Tool object from a function and register it automatically.
    """
    def wrapper(func: Callable[..., Any]):
        tool_obj = Tool(
            name=name or func.__name__,
            category=category,
            description=description,
            context=context,
            parameters=parameters,
            func=func
        )

        # Register the tool automatically
        TOOL_REGISTRY[tool_obj.name] = tool_obj

        return func  # return original function for IDE tooltips and normal calls

    return wrapper



class ToolEmbeddings:

    def __init__(self, path=r".\Tools\tool_embeddings.jsonl"):
        
        self.path = path
        self.tools = self._load_tool_vectors()

    def _load_tool_vectors(self):
        """
        Loads tool embeddings from JSONL file. 
        Returns a list of dicts with numpy embeddings.
        """
        tools = []

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                record = json.loads(line)
                record["embedding"] = np.array(record["embedding"], dtype=np.float32)
                tools.append(record)

        return tools
    

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(
            np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8)
        )
    
    
    def search_tools(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Returns top_k tools ranked by cosine similarity.
        """

        query_embedding = query_embedding.astype(np.float32)

        scored = []
        for tool in self.tools:
            score = self._cosine_similarity(query_embedding, tool["embedding"])
            scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "score": score,
                "tool_name": tool["tool_name"],
                "description": tool["description"],
                "metadata": tool.get("metadata", {}),
            }
            for score, tool in scored[:top_k]
        ]
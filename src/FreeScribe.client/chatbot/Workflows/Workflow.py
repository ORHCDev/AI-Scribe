import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowContext:
    ai_conn: Any
    db_conn: Any
    oscar: Any
    vec_search: Any
    tools: Any
    conversation_history: list
    curr_demo: str
    prompts: dict

@dataclass
class WorkflowEntry:
    name: str
    description: str
    keywords: list[str]
    workflow_class: type

@dataclass
class WorkflowResult:
    response: str
    sources: list | None = None

# this class is an abstract method of the actual workflows
class Workflow(ABC):
    @abstractmethod
    def run(self, user_input: str, context: WorkflowContext) -> WorkflowResult:
        pass

# stores all the workflow entrys, uses class method to act as a global state container
class WorkflowRegistry:
    _registry: dict[str, WorkflowEntry] = {}

    @classmethod
    def register(cls, name: str, description: str, keywords: list[str]):
        def decorator(workflow_cls: type[Workflow]):
            cls._registry[name] = WorkflowEntry(
                name=name,
                description=description,
                keywords=keywords,
                workflow_class=workflow_cls
            )
            return workflow_cls
        return decorator

    @classmethod
    def instantiate(cls, name: str) -> Workflow:
        if name not in cls._registry:
            raise KeyError(f"Workflow '{name}' not registered. Available: {list(cls._registry.keys())}")
        return cls._registry[name].workflow_class()

    @classmethod
    def instantiate_all(cls) -> dict[str, Workflow]:
        return {name: cls.instantiate(name) for name in cls._registry}

    @classmethod
    def classify(cls, user_input: str, context: WorkflowContext) -> str:
        desc_str = "\n".join(
            f"{entry.name}: {entry.description} | Keywords: {', '.join(entry.keywords)}"
            for entry in cls._registry.values()
        )
        history_str = "\n".join(context.conversation_history) if context.conversation_history else "None"
        prompt = context.prompts.get("workflow_prompt").format(
            workflow_protocol=context.prompts.get("workflow_protocol"),
            workflow_descriptions=desc_str,
            history=history_str,
            user_input=user_input
        )
        result = context.ai_conn.send_message(prompt)
        result = result.replace("```json", "").replace("```", "").replace("**JSON only**", "").strip()
        result_json = json.loads(result)
        workflow_type = result_json.get("workflow", "rag_search").lower()
        return workflow_type if workflow_type in cls._registry else "rag_search"


def workflow(name: str, description: str, keywords: list[str]):
    return WorkflowRegistry.register(name=name, description=description, keywords=keywords)

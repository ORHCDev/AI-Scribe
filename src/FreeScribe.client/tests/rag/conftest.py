"""
Fixtures for the RAG unit tests: stub the heavy runtime deps when missing and
load the modules under test straight from their .py files by path.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_CLIENT_ROOT = _HERE.parent.parent
_RAG_DIR = _CLIENT_ROOT / "chatbot" / "RAG"
_EVAL_DIR = _RAG_DIR / "eval"


def _install_stub(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _stub_if_missing(name, factory):
    try:
        __import__(name)
    except Exception:
        factory()


def _make_numpy_stub():
    class _Sub:  # subscriptable dummy for annotations like `np.ndarray[786]`
        def __class_getitem__(cls, _item):
            return cls

    # No log1p etc., so tests needing real numpy skip via hasattr(np, "log1p").
    # isscalar/bool_/ndarray are what pytest.approx probes on sys.modules['numpy'].
    _install_stub(
        "numpy",
        ndarray=_Sub,
        float64=_Sub,
        bool_=type("_bool_", (), {}),
        isscalar=lambda o: isinstance(o, (int, float, complex, bool, str, bytes)),
    )


def _make_psycopg2_stub():
    def _connect(*_a, **_k):
        raise RuntimeError("psycopg2 is stubbed in tests")

    _install_stub("psycopg2", connect=_connect)


def _make_sentence_transformers_stub():
    class _Model:
        def __init__(self, *_a, **_k):
            pass

        def encode(self, *_a, **_k):
            raise RuntimeError("SentenceTransformer is stubbed in tests")

        def predict(self, *_a, **_k):
            raise RuntimeError("CrossEncoder is stubbed in tests")

    _install_stub("sentence_transformers", SentenceTransformer=_Model, CrossEncoder=_Model)


def _make_tool_stub():
    # For VectorSearch's `from chatbot.Tools.Tool import ToolEmbeddings`.
    pkg = _install_stub("chatbot")
    pkg.__path__ = []
    tools = _install_stub("chatbot.Tools")
    tools.__path__ = []

    class _ToolEmbeddings:
        pass

    tool = _install_stub("chatbot.Tools.Tool", ToolEmbeddings=_ToolEmbeddings)
    pkg.Tools = tools
    tools.Tool = tool


def _make_tools_utils_stub():
    # For embedder's `from Tools.utils import pdf_image_to_text`.
    pkg = _install_stub("Tools")
    pkg.__path__ = []
    util = _install_stub("Tools.utils", pdf_image_to_text=lambda *_a, **_k: "")
    pkg.utils = util


def _make_rag_chunker_stub():
    # For embedder's `from RAG.chunker import Chunker`.
    pkg = _install_stub("RAG")
    pkg.__path__ = []

    class _Chunker:
        def __init__(self, *_a, **_k):
            pass

    ch = _install_stub("RAG.chunker", Chunker=_Chunker)
    pkg.chunker = ch


_stub_if_missing("numpy", _make_numpy_stub)
_stub_if_missing("psycopg2", _make_psycopg2_stub)
_stub_if_missing("sentence_transformers", _make_sentence_transformers_stub)
_stub_if_missing("chatbot.Tools.Tool", _make_tool_stub)
_stub_if_missing("pandas", lambda: _install_stub("pandas"))
_stub_if_missing("yaml", lambda: _install_stub("yaml", safe_load=lambda *_a, **_k: {}))
_stub_if_missing("Tools.utils", _make_tools_utils_stub)
_stub_if_missing("RAG.chunker", _make_rag_chunker_stub)


def _load_from_path(mod_name, file_path):
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def vectorsearch_mod():
    return _load_from_path("_rag_vectorsearch_under_test", _RAG_DIR / "VectorSearch.py")


@pytest.fixture(scope="session")
def metrics_mod():
    return _load_from_path("_rag_eval_metrics", _EVAL_DIR / "metrics.py")


@pytest.fixture(scope="session")
def embedder_mod():
    return _load_from_path("_rag_embedder_under_test", _RAG_DIR / "embedder.py")


@pytest.fixture(scope="session")
def ragworkflow_mod():
    # Register the pure-stdlib Workflow module under the name RAGWorkflow imports.
    wf = _load_from_path(
        "chatbot.Workflows.Workflow",
        _CLIENT_ROOT / "chatbot" / "Workflows" / "Workflow.py",
    )
    chatbot = sys.modules.get("chatbot")
    if chatbot is None:
        chatbot = _install_stub("chatbot")
        chatbot.__path__ = []
    workflows = sys.modules.get("chatbot.Workflows")
    if workflows is None:
        workflows = _install_stub("chatbot.Workflows")
        workflows.__path__ = []
    chatbot.Workflows = workflows
    workflows.Workflow = wf
    return _load_from_path(
        "_rag_workflow_under_test",
        _CLIENT_ROOT / "chatbot" / "Workflows" / "RAGWorkflow.py",
    )

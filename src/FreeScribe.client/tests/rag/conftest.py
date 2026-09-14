"""
Shared fixtures for the RAG bug-level unit tests.

These tests are designed to run on ANY machine, including ones that do not have
the heavy RAG runtime installed (numpy / psycopg2 / sentence-transformers).
The modules under test import those packages at module load time, so we install
lightweight stand-ins in ``sys.modules`` for the ones that are missing *before*
loading the source files directly by path.

Rules:
  * We only stub a dependency when the real one cannot be imported. On the
    RAG server (where everything is installed) the real packages are used.
  * numpy is special: the reranking math genuinely needs it, so we never fake
    the math. Tests that need real numpy detect it via ``hasattr(np, "log1p")``
    and skip when only the tiny stub is present.
  * The modules under test are loaded straight from their .py files under
    private module names, so we never depend on the (inconsistent) package
    layout under ``chatbot/``.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_CLIENT_ROOT = _HERE.parent.parent                 # src/FreeScribe.client
_RAG_DIR = _CLIENT_ROOT / "chatbot" / "RAG"
_EVAL_DIR = _RAG_DIR / "eval"


def _install_stub(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _stub_if_missing(name, factory):
    """Install a stub for ``name`` only if the real package cannot be imported."""
    try:
        __import__(name)
        return  # real dependency present -> use it
    except Exception:
        factory()


def _make_numpy_stub():
    class _Sub:  # subscriptable dummy for annotations like `np.ndarray[786]`
        def __class_getitem__(cls, _item):
            return cls

    # Only the names evaluated while importing VectorSearch.py (used in type
    # annotations: ndarray, float64) plus the three attributes pytest.approx
    # probes on sys.modules['numpy'] (isscalar, bool_, ndarray) are provided.
    # We deliberately do NOT provide log1p etc., so tests that need the real
    # numpy detect its absence via ``hasattr(np, "log1p")`` and skip.
    _install_stub(
        "numpy",
        ndarray=_Sub,
        float64=_Sub,
        bool_=type("_bool_", (), {}),
        isscalar=lambda o: isinstance(o, (int, float, complex, bool, str, bytes)),
    )


def _make_psycopg2_stub():
    def _connect(*_a, **_k):
        raise RuntimeError("psycopg2 is stubbed in tests; do not open a real connection")

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
    # VectorSearch.py does ``from chatbot.Tools.Tool import ToolEmbeddings`` at import
    # time. Register fake parent packages so that import resolves without pulling in
    # the real Tool.py (which needs pandas/numpy).
    pkg = _install_stub("chatbot")
    pkg.__path__ = []
    tools = _install_stub("chatbot.Tools")
    tools.__path__ = []

    class _ToolEmbeddings:  # only the name is needed at import time
        pass

    tool = _install_stub("chatbot.Tools.Tool", ToolEmbeddings=_ToolEmbeddings)
    pkg.Tools = tools
    tools.Tool = tool


_stub_if_missing("numpy", _make_numpy_stub)
_stub_if_missing("psycopg2", _make_psycopg2_stub)
_stub_if_missing("sentence_transformers", _make_sentence_transformers_stub)
_stub_if_missing("chatbot.Tools.Tool", _make_tool_stub)


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

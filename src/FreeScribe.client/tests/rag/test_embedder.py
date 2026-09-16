"""
Measurement text-building tests. Former BUG: a type missing from the YAML
(EXAM absent, RISK spelled "Risk") KeyError'd and aborted the whole upsert.
"""

from pathlib import Path

_YAML = (
    Path(__file__).resolve().parents[2]
    / "chatbot" / "RAG" / "measurement_descriptions.yaml"
)


def _make_engine(embedder_mod, descriptions):
    Engine = embedder_mod.EmbeddingEngine
    eng = Engine.__new__(Engine)
    eng.descriptions = descriptions
    return eng


def test_build_text_includes_description_when_present(embedder_mod):
    eng = _make_engine(embedder_mod, {"ECHO": "Echocardiography findings."})
    out = eng._build_measurement_text("ECHO", "2024-01-04", "EF 55%")
    assert "Type:ECHO" in out
    assert "Description:Echocardiography findings." in out
    assert "Content:EF 55%" in out


def test_build_text_missing_type_does_not_crash(embedder_mod):
    eng = _make_engine(embedder_mod, {"ECHO": "x"})
    out = eng._build_measurement_text("EXAM", "2024-01-04", "normal cardiac exam")
    assert "Type:EXAM" in out
    assert "Content:normal cardiac exam" in out
    assert "Description:" not in out


def test_build_text_without_descriptions_returns_raw(embedder_mod):
    eng = _make_engine(embedder_mod, None)
    out = eng._build_measurement_text("ECHO", "2024-01-04", "EF 55%")
    assert out == "EF 55%"


def test_descriptions_yaml_covers_exam_and_risk():
    text = _YAML.read_text(encoding="utf-8")
    assert "EXAM:" in text
    assert "RISK:" in text

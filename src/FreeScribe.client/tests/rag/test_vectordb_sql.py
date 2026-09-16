"""Tests for the SQL that VectorDB.search builds (captured via a fake cursor)."""

import pytest


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return [0]

    def close(self):
        pass


def _make_vdb(vectorsearch_mod):
    VectorDB = vectorsearch_mod.VectorDB
    vdb = VectorDB.__new__(VectorDB)
    vdb.cursor = _FakeCursor()
    vdb.conn = None
    return vdb


def _last_sql(vdb):
    return vdb.cursor.executed[-1][0]


def test_patient_filter_appears_in_sql(vectorsearch_mod):
    vdb = _make_vdb(vectorsearch_mod)
    vdb.search(
        table_name="measurement_chunks",
        columns=["chunk_text"],
        vector_col="embedding_raw",
        query_vec=[0.1, 0.2, 0.3],
        patient_filter={"column": "demographic_no", "value": 4},
    )
    sql = _last_sql(vdb)
    assert "demographic_no = 4" in sql
    assert "ORDER BY distance" in sql
    assert "LIMIT" in sql


def test_exact_date_filter_appears_in_sql(vectorsearch_mod):
    vdb = _make_vdb(vectorsearch_mod)
    vdb.search(
        table_name="measurement_chunks",
        columns=["chunk_text"],
        vector_col="embedding_raw",
        query_vec=[0.1, 0.2],
        date_filter={"column": "observation_date", "value": "2024-01-04"},
    )
    assert "DATE(observation_date) = '2024-01-04'" in _last_sql(vdb)


# Regression for former BUG #1: date_delta must widen to a +/-N day range.
def test_date_delta_produces_a_range(vectorsearch_mod):
    vdb = _make_vdb(vectorsearch_mod)
    vdb.search(
        table_name="measurement_chunks",
        columns=["chunk_text"],
        vector_col="embedding_raw",
        query_vec=[0.1, 0.2],
        date_filter={"column": "observation_date", "value": "2024-01-04", "delta": 3},
    )
    assert "DATE(observation_date) BETWEEN '2024-01-01' AND '2024-01-07'" in _last_sql(vdb)


# BUG #5 (still open): filter values are f-string-formatted, not parameterized.
@pytest.mark.xfail(strict=True, reason="BUG #5: VectorDB.search f-strings values into SQL (injectable)")
def test_date_value_is_not_injectable(vectorsearch_mod):
    vdb = _make_vdb(vectorsearch_mod)
    vdb.search(
        table_name="measurement_chunks",
        columns=["chunk_text"],
        vector_col="embedding_raw",
        query_vec=[0.1, 0.2],
        date_filter={"column": "observation_date", "value": "2024-01-04' OR '1'='1"},
    )
    sql, _params = vdb.cursor.executed[-1]
    assert "OR '1'='1'" not in sql

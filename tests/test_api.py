"""API 集成测试：端点闭环（TestClient 直连，无需起服务）。"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402

client = TestClient(app)


# ---------- 基础端点 ----------

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["agents"] == 5
    assert r.json()["tasks"] == 8


def test_ontology():
    r = client.get("/api/ontology")
    assert r.status_code == 200
    d = r.json()
    assert len(d["individuals"]) == 13
    assert {e["property"] for e in d["edges"]} >= {"has_capability", "can_execute", "depends_on"}


def test_index_page():
    # GET / 优先返回新前端（frontend/app/dist，Vite 构建）；未构建时回退旧单页
    r = client.get("/")
    assert r.status_code == 200
    assert ("本体图谱工作台" in r.text) or ("本体图谱展示" in r.text)


# ---------- 推理端点 ----------

def test_reason_capability_match():
    r = client.post("/api/reason", json={"type": "capability_match", "task": "t_login_dev"})
    assert r.status_code == 200
    names = {m["agent"] for m in r.json()["matches"]}
    assert {"dev_agent", "junior_dev"} <= names


def test_reason_orchestrate():
    r = client.post("/api/reason", json={"type": "orchestrate", "task": "t_feature"})
    assert r.status_code == 200
    plan = r.json()
    assert len(plan["steps"]) == 5
    assert plan["steps"][0]["task"] == "t_req"


def test_reason_assign_conflict():
    r = client.post("/api/reason", json={"type": "assign", "task": "t_compliance_dev", "agent": "junior_dev"})
    assert r.status_code == 200
    assert r.json()["conflict"] is not None


def test_classify():
    r = client.post("/api/classify", json={
        "name": "t_api_classify", "capabilities": ["Coding"],
        "constraints": ["ComplianceRequirement"], "risk_level": 5,
    })
    assert r.status_code == 200
    assert {"ComplianceTask", "HighRiskTask"} <= {t["class"] for t in r.json()["inferred_types"]}


def test_explain():
    client.post("/api/reason", json={"type": "capability_match", "task": "t_login_dev"})
    r = client.post("/api/explain")
    assert r.status_code == 200
    assert r.json()["query_kind"] == "capability_match"
    assert len(r.json()["derivation"]) > 0


def test_consistency():
    r = client.post("/api/consistency")
    assert r.status_code == 200
    assert "consistent" in r.json()

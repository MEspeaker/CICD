import json
import pytest
from app import app

@pytest.fixture
def client():
    return app.test_client()

def test_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"TFT Top Tracker" in resp.data  # 제목 존재

def test_api_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = json.loads(resp.data)
    # 기본 구조
    assert "total_matches" in data
    assert "total_summoners" in data
    assert "matches_by_tier" in data
    assert isinstance(data["total_matches"], int)
    assert isinstance(data["total_summoners"], int)
    assert isinstance(data["matches_by_tier"], dict)

def test_api_matches(client):
    resp = client.get("/api/matches")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = json.loads(resp.data)
    assert "matches" in data
    assert "total" in data
    assert isinstance(data["matches"], list)
    assert isinstance(data["total"], int)

def test_api_tiers(client):
    resp = client.get("/api/tiers")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    assert "tiers" in data
    # 기본값은 CHALLENGER / GRANDMASTER / MASTER
    assert all(t in {"CHALLENGER", "GRANDMASTER", "MASTER"} for t in data["tiers"])

def test_api_matches_by_tier(client):
    resp = client.get("/api/matches/by-tier/CHALLENGER")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    assert "matches" in data and isinstance(data["matches"], list)
    assert "total" in data and isinstance(data["total"], int)
    assert data.get("tier") in {"CHALLENGER", "GRANDMASTER", "MASTER", "CHALLENGER"}

def test_api_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    data = resp.get_json()
    for key in ["ok", "has_api_key", "data_dir", "matches_file_exists", "summoners_count"]:
        assert key in data

def test_collect_endpoint_mocked(client, monkeypatch):
    """수집 엔드포인트는 외부 API를 호출하므로 모킹해서 성공 경로만 검증"""
    from collector import collect_top_matches as real_collect

    def fake_collect(platform_region="kr", max_players=50, max_matches_per_player=10, tiers=None):
        return {
            "platform_region": platform_region,
            "tiers": tiers or ["challenger", "grandmaster", "master"],
            "players_collected": 1,
            "matches_fetched": 2,
            "duration_sec": 0.12,
        }

    monkeypatch.setattr("collector.collect_top_matches", fake_collect)
    resp = client.post("/collect?region=kr&players=1&per_player=1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["players_collected"] == 1
    assert data["matches_fetched"] == 2

def test_html_static_files(client):
    resp = client.get("/html/index.html")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"TFT Top Tracker" in resp.data

  
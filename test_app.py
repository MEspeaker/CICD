import pytest
from app import app
import json

@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()

def test_root_returns_html(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data

def test_api_stats(client):
    resp = client.get('/api/stats')
    assert resp.status_code == 200
    assert resp.content_type.startswith('application/json')

    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert 'total_matches' in data
    assert 'total_summoners' in data
    assert 'matches_by_tier' in data
    assert isinstance(data['total_matches'], int)
    assert isinstance(data['total_summoners'], int)

def test_api_matches(client):
    resp = client.get('/api/matches')
    assert resp.status_code == 200
    assert resp.content_type.startswith('application/json')

    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert 'matches' in data
    assert 'total' in data
    assert isinstance(data['matches'], list)
    assert isinstance(data['total'], int)

def test_collect_endpoint(client, monkeypatch):
    # 외부 API 호출을 막고 항상 성공적인 수집 결과를 반환하도록 목킹
    import collector
    monkeypatch.setattr(
        collector,
        "collect_top_matches",
        lambda *args, **kwargs: {
            "platform_region": "kr",
            "tiers": ["challenger"],
            "players_collected": 1,
            "matches_fetched": 1,
            "duration_sec": 0.01,
        },
    )

    resp = client.post('/collect?region=kr&players=1&per_player=1')
    assert resp.status_code == 200
    data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp.data)
    assert data["players_collected"] == 1
    assert data["matches_fetched"] == 1
    assert data["platform_region"] == "kr"

def test_html_static_files(client):
    resp = client.get('/html/index.html')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data


  
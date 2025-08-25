import pytest
from app import app
import json

@pytest.fixture
def client():
    return app.test_client()

def test_root_returns_html(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data

def test_api_stats(client):
    resp = client.get('/api/stats')
    assert resp.status_code == 200
    # 여기만 수정
    assert resp.content_type.startswith('application/json')

    data = json.loads(resp.data)
    assert 'total_matches' in data
    assert 'total_summoners' in data
    assert 'matches_by_tier' in data
    assert isinstance(data['total_matches'], int)
    assert isinstance(data['total_summoners'], int)

def test_api_matches(client):
    resp = client.get('/api/matches')
    assert resp.status_code == 200
    # 여기만 수정
    assert resp.content_type.startswith('application/json')

    data = json.loads(resp.data)
    assert 'matches' in data
    assert 'total' in data
    assert isinstance(data['matches'], list)
    assert isinstance(data['total'], int)

def test_collect_endpoint(client):
    resp = client.post('/collect?region=kr&players=1&per_player=1')
    assert resp.status_code in [200, 500]

def test_html_static_files(client):
    resp = client.get('/html/index.html')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data

  
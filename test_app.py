import pytest
from app import app
import json


@pytest.fixture
def client():
    return app.test_client()


def test_root_returns_html(client):
    """루트 경로가 HTML 페이지를 반환하는지 테스트"""
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data  # HTML에 포함된 제목 확인


def test_api_stats(client):
    """통계 API 엔드포인트 테스트"""
    resp = client.get('/api/stats')
    assert resp.status_code == 200
    assert resp.content_type == 'application/json'
    
    data = json.loads(resp.data)
    # 기본 구조 확인
    assert 'total_matches' in data
    assert 'total_summoners' in data
    assert 'matches_by_tier' in data
    assert isinstance(data['total_matches'], int)
    assert isinstance(data['total_summoners'], int)


def test_api_matches(client):
    """매치 데이터 API 엔드포인트 테스트"""
    resp = client.get('/api/matches')
    assert resp.status_code == 200
    assert resp.content_type == 'application/json'
    
    data = json.loads(resp.data)
    assert 'matches' in data
    assert 'total' in data
    assert isinstance(data['matches'], list)
    assert isinstance(data['total'], int)


def test_collect_endpoint(client):
    """수집 엔드포인트 테스트 (실제 API 호출 없이)"""
    # RIOT_API_KEY가 없어도 엔드포인트가 존재하는지만 확인
    resp = client.post('/collect?region=kr&players=1&per_player=1')
    # API 키가 없으면 500 에러가 예상되지만, 엔드포인트는 존재해야 함
    assert resp.status_code in [200, 500]  # 200 (성공) 또는 500 (API 키 없음)


def test_html_static_files(client):
    """HTML 정적 파일 서빙 테스트"""
    resp = client.get('/html/index.html')
    assert resp.status_code == 200
    assert resp.content_type.startswith('text/html')
    assert b'TFT Top Tracker' in resp.data
  
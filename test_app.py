import pytest
from app import app


@pytest.fixture
def client():
    return app.test_client()


def test_root(client):
    resp = client.get('/')
    assert resp.data == b'TFT Tracker is running'
  
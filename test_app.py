import pytest
from app import app

@pytest.fixture
def client():
  return app.test_client()

def test_hello(client):
  resp= client.get('/')
  assert resp.data== b'Fucking, Flask!'
  
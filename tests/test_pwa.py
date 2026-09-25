import json
from fastapi.testclient import TestClient
from src.app import server


def test_pwa_manifest_is_served_from_scope_root():
    client = TestClient(server.app)
    r = client.get('/manifest.webmanifest')
    assert r.status_code == 200
    assert 'application/manifest+json' in r.headers['content-type']
    data = r.json()
    assert data['name'].startswith('Otherwise')
    assert data['start_url'] == '/'
    assert data['scope'] == '/'
    assert data['display'] == 'standalone'
    assert any(icon.get('sizes') == '512x512' for icon in data['icons'])


def test_service_worker_has_root_scope_and_no_api_cache():
    client = TestClient(server.app)
    r = client.get('/sw.js')
    assert r.status_code == 200
    assert r.headers.get('service-worker-allowed') == '/'
    assert 'no-cache' in r.headers.get('cache-control', '')
    assert 'url.pathname.startsWith("/api/")' in r.text

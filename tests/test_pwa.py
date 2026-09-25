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


def test_service_worker_is_network_first_for_html_and_static():
    """A deploy must never be masked by a stale cache on someone's phone: pages
    and static assets go to the network first, and the cache is only the offline
    fallback. Guard against a cache-first handler creeping back in."""
    sw = TestClient(server.app).get('/sw.js').text
    assert 'req.mode === "navigate"' in sw and 'networkFirst(req, "/")' in sw
    assert 'url.pathname.startsWith("/static/")' in sw and 'networkFirst(req, null)' in sw
    assert 'fetch(req, { cache: "no-cache" })' in sw
    assert 'caches.match(req).then((cached) => cached ||' not in sw   # the old cache-first pattern
    assert 'res.ok' in sw                                              # errors are never cached


def test_manifest_icons_exist_and_pages_link_the_manifest():
    import os
    client = TestClient(server.app)
    for icon in client.get('/manifest.webmanifest').json()['icons']:
        assert client.get(icon['src']).status_code == 200, icon['src']
    web = server.WEB_DIR
    for page in ('index.html', 'verdict.html', 'track.html', 'batch.html'):
        html = open(os.path.join(web, page), encoding='utf-8').read()
        assert 'rel="manifest" href="/manifest.webmanifest"' in html, page
        assert '/static/pwa.js' in html, page

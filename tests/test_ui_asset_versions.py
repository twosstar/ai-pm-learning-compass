import hashlib


def test_html_and_assets_are_uncached_and_use_content_versions(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    with TestClient(main.app) as client:
        response = client.get('/?ui=cache-regression')
        assert response.status_code == 200
        assert 'no-store' in response.headers['cache-control']
        first_version = response.headers['x-learning-ui-version']
        for asset in ('app.js', 'styles.css', 'progress.js'):
            expected = hashlib.sha256((main.STATIC_DIR / asset).read_bytes()).hexdigest()[:12]
            locator = f'/static/{asset}?v={expected}'
            assert locator in response.text
            assert 'no-store' in client.get(locator).headers['cache-control']
        class RevisedHash:
            def hexdigest(self):
                return 'f' * 64

        monkeypatch.setattr(main.hashlib, 'sha256', lambda value: RevisedHash())
        revised = client.get('/')
        assert revised.headers['x-learning-ui-version'] != first_version
        assert '/static/app.js?v=ffffffffffff' in revised.text

"""Public landing page and manual access requests never provision customers."""
import os
from pathlib import Path
import subprocess
import sys
import time
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from test_saas import (
    PUBLIC, account, assert_denied, login, make_key, saas_env,
)
from test_admin_auth import AUTH, admin_login


REQUESTS = '/saas/api/access-requests'
ADMIN_REQUESTS = '/saas/api/admin/access-requests'
PAYLOAD = {'name': 'Nguyễn An', 'email': 'an@example.com', 'purpose': 'Lồng tiếng'}
ASSETS = ('homepage.css', 'homepage.js', 'demo-male.wav', 'demo-female.wav')
OPTIONAL_ASSETS = ('favicon.svg', 'font-latin.woff2', 'font-vietnamese.woff2')


def rows():
    from apps import saas
    with saas.connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM access_requests ORDER BY created_at, id')]


def provision_state():
    from apps import saas
    with saas.connect() as db:
        return {table: sorted(tuple(row) for row in db.execute('SELECT * FROM ' + table))
                for table in ('users', 'plans', 'settings', 'sessions', 'api_keys', 'usage_jobs')}


@pytest.fixture
def landing_files(tmp_path, monkeypatch):
    """Exercise file serving before frontend delivery, without touching agent files."""
    from apps import saas
    directory = tmp_path / 'landing_static'
    directory.mkdir()
    (directory / 'homepage.html').write_text(
        '<!doctype html><html><head><link rel="canonical" href="__PUBLIC_URL__/"></head>'
        '<body>Public homepage</body></html>', encoding='utf-8')
    for name in ASSETS + OPTIONAL_ASSETS:
        (directory / name).write_bytes(b'RIFF-test-WAVE' if name.endswith('.wav') else b'public asset')
    (directory / 'private.txt').write_text('PRIVATE-FILE-MUST-NOT-LEAK')
    (tmp_path / 'secret.txt').write_text('PARENT-FILE-MUST-NOT-LEAK')
    monkeypatch.setattr(saas, '__file__', str(tmp_path / 'saas.py'))
    return directory


class PageLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.canonicals = []
        self.assets = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and 'canonical' in attrs.get('rel', '').split():
            self.canonicals.append(attrs.get('href'))
        for key in ('src', 'href'):
            value = attrs.get(key, '')
            if '/saas/landing-assets/' in value:
                self.assets.append(value)


def test_anonymous_homepage_uses_configured_canonical(saas_env, landing_files):
    client = saas_env[2]
    before = provision_state()
    response = client.get('/saas/homepage', headers={'X-Forwarded-Host': 'evil.example'})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'].startswith('text/html')
    assert PageLinks(response.text).canonicals == [PUBLIC + '/']
    assert '__PUBLIC_URL__' not in response.text
    assert 'evil.example' not in response.text
    assert not client.cookies
    assert provision_state() == before


@pytest.mark.parametrize('name', ASSETS + OPTIONAL_ASSETS)
def test_public_asset_exact_whitelist(saas_env, landing_files, name):
    response = saas_env[2].get('/saas/landing-assets/' + name)
    assert response.status_code == 200, response.text
    assert response.content == (landing_files / name).read_bytes()


@pytest.mark.parametrize('name', [
    'private.txt', 'homepage.html', 'saas.sqlite3', 'Homepage.css', 'homepage.css.bak',
    'unknown.woff2', 'homepage.js.map', '%2e%2e%2fsecret.txt',
    '..%5csecret.txt', '%252e%252e%252fsecret.txt', 'sub/homepage.css',
    '%2e%2e%2flanding_static%2fhomepage.css', 'homepage.css%00',
])
def test_unknown_and_traversal_assets_are_404(saas_env, landing_files, name):
    response = saas_env[2].get('/saas/landing-assets/' + name, follow_redirects=False)
    assert response.status_code == 404, response.text
    assert 'MUST-NOT-LEAK' not in response.text


@pytest.mark.parametrize('path', ['/saas/homepage', '/saas/landing-assets/homepage.css',
                                  '/saas/robots.txt', '/saas/sitemap.xml'])
def test_public_landing_routes_are_selfhost_only(saas_env, landing_files, monkeypatch, path):
    monkeypatch.setenv('CIT_DEPLOYMENT_MODE', 'desktop')
    with TestClient(saas_env[0], base_url='http://127.0.0.1', client=('127.0.0.1', 1234)) as local:
        assert local.get(path).status_code == 404


def test_delivered_homepage_and_referenced_assets(saas_env):
    from apps import saas
    page = Path(saas.__file__).with_name('landing_static') / 'homepage.html'
    if not page.is_file():
        pytest.skip('Landing frontend has not been delivered; isolated file-serving tests still run')
    response = saas_env[2].get('/saas/homepage')
    assert response.status_code == 200, response.text
    links = PageLinks(response.text)
    assert links.canonicals == [PUBLIC + '/']
    assert '__PUBLIC_URL__' not in response.text
    for name in ASSETS:
        assert saas_env[2].get('/saas/landing-assets/' + name).status_code == 200
    for url in links.assets:
        assert saas_env[2].get(url).status_code == 200, url


@pytest.mark.parametrize('origin', [None, PUBLIC])
def test_anonymous_request_is_manual_and_never_provisions(saas_env, origin):
    client = saas_env[2]
    before = provision_state()
    headers = {} if origin is None else {'Origin': origin}
    response = client.post(REQUESTS, json=PAYLOAD, headers=headers)
    assert response.status_code == 200, response.text
    item, = rows()
    assert {key: item[key] for key in PAYLOAD} == PAYLOAD
    assert item['id'] and item['status'] == 'new'
    assert isinstance(item['created_at'], (int, float))
    assert abs(time.time() - item['created_at']) < 30
    assert 'website' not in item
    assert not client.cookies
    assert provision_state() == before
    assert_denied(client.get('/saas/api/me'))


def test_optional_purpose_and_website_default_empty(saas_env):
    assert saas_env[2].post(REQUESTS, json={'name': 'An', 'email': 'an@example.com'}).status_code == 200
    assert rows()[0]['purpose'] == ''


@pytest.mark.parametrize('origin', ['https://evil.example', PUBLIC + '.evil.example',
                                  PUBLIC + ':444', PUBLIC + '/', 'null'])
def test_access_request_origin_must_match_exactly(saas_env, origin):
    before = provision_state()
    assert_denied(saas_env[2].post(REQUESTS, json=PAYLOAD, headers={'Origin': origin}))
    assert rows() == []
    assert provision_state() == before


@pytest.mark.parametrize('change', [
    {'name': 'private-name-' + 'x' * 101},
    {'email': 'private-email-' + 'x' * 254 + '@example.com'},
    {'purpose': 'private-purpose-' + 'x' * 1001},
    {'name': None}, {'email': None}, {'purpose': None},
])
def test_validation_limits_redact_raw_input(saas_env, change):
    payload = {**PAYLOAD, **change}
    response = saas_env[2].post(REQUESTS, json=payload)
    assert response.status_code == 422, response.text
    for value in payload.values():
        if isinstance(value, str):
            assert value not in response.text
    for error in response.json()['detail']:
        assert set(error) <= {'loc', 'msg', 'type'}
    assert rows() == []


@pytest.mark.parametrize('payload', [
    {}, {'name': 'An'}, {'email': 'an@example.com'},
    {**PAYLOAD, 'name': ''}, {**PAYLOAD, 'name': '   '},
    {**PAYLOAD, 'email': 'not-an-email'},
])
def test_missing_or_invalid_contact_is_not_stored(saas_env, payload):
    assert saas_env[2].post(REQUESTS, json=payload).status_code == 422
    assert rows() == []


def test_maximum_field_lengths_are_accepted(saas_env):
    email = 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 61
    assert len(email) == 254
    payload = {'name': 'N' * 100, 'email': email, 'purpose': 'P' * 1000}
    response = saas_env[2].post(REQUESTS, json=payload)
    assert response.status_code == 200, response.text
    assert {key: rows()[0][key] for key in payload} == payload


def test_honeypot_and_duplicate_have_same_generic_response(saas_env):
    client = saas_env[2]
    before = provision_state()
    trapped = client.post(REQUESTS, json={**PAYLOAD, 'website': 'https://spam.example'})
    assert trapped.status_code == 200
    assert rows() == []
    accepted = client.post(REQUESTS, json=PAYLOAD)
    original = rows()
    duplicate = client.post(REQUESTS, json={**PAYLOAD, 'name': 'Replacement', 'purpose': 'overwrite'})
    assert accepted.status_code == duplicate.status_code == 200
    assert trapped.json() == accepted.json() == duplicate.json()
    assert len(original) == 1
    assert rows() == original
    assert provision_state() == before


def test_dedup_normalizes_email_and_expires_after_24_hours(saas_env):
    from apps import saas
    client = saas_env[2]
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    assert client.post(REQUESTS, json={**PAYLOAD, 'email': ' AN@EXAMPLE.COM '}).status_code == 200
    assert len(rows()) == 1
    with saas.connect() as db:
        db.execute('UPDATE access_requests SET created_at=?', (time.time() - 86340,))
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    assert len(rows()) == 1
    with saas.connect() as db:
        db.execute('UPDATE access_requests SET created_at=?', (time.time() - 86460,))
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    assert len(rows()) == 2


def test_access_abuse_is_throttled_without_poisoning_login(saas_env):
    app, _, client, _ = saas_env
    before = provision_state()
    statuses = [client.post(REQUESTS, json=PAYLOAD).status_code for _ in range(9)]
    assert statuses[:8] == [200] * 8
    assert statuses[8] == 429
    assert len(rows()) == 1
    assert provision_state() == before
    # Same peer, real owner credentials: access request buckets are separate.
    admin_login(client)
    assert client.get(ADMIN_REQUESTS).status_code == 200
    with TestClient(app, base_url=PUBLIC, client=('203.0.113.99', 1234)) as other:
        assert other.post(REQUESTS, json=PAYLOAD).status_code == 429
        assert other.post(REQUESTS, json={**PAYLOAD, 'email': 'other@example.com'}).status_code == 200


def test_peer_limit_cannot_be_bypassed_with_distinct_emails(saas_env):
    client = saas_env[2]
    for index in range(60):
        response = client.post(REQUESTS, json={**PAYLOAD, 'email': f'person{index}@example.com'})
        assert response.status_code == 200, (index, response.text)
    assert client.post(REQUESTS, json={**PAYLOAD, 'email': 'one-more@example.com'}).status_code == 429
    assert len(rows()) == 60


def test_admin_list_and_status_changes_store_text_without_rendering(saas_env, landing_files):
    _, admin, client, _ = saas_env
    payload = {**PAYLOAD, 'name': '<img src=x onerror=alert(1)>',
               'purpose': '<script>alert("purpose")</script>'}
    before = provision_state()
    assert client.post(REQUESTS, json=payload).status_code == 200
    item, = rows()
    response = admin.get(ADMIN_REQUESTS)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.json() == {'items': [item]}
    assert item['name'] == payload['name'] and item['purpose'] == payload['purpose']
    for status in ('reviewed', 'closed', 'new'):
        response = admin.patch(ADMIN_REQUESTS + '/' + item['id'], json={'status': status},
                               headers={'Origin': PUBLIC})
        assert response.status_code == 200, response.text
        expected = {**item, 'status': status}
        assert rows() == [expected]
        assert admin.get(ADMIN_REQUESTS).json() == {'items': [expected]}
    page = client.get('/saas/homepage')
    assert page.status_code == 200
    assert payload['name'] not in page.text and payload['purpose'] not in page.text
    assert provision_state() == before


def test_anonymous_and_customer_cannot_list_or_patch(saas_env, account):
    _, _, client, _ = saas_env
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    item, = rows()
    path = ADMIN_REQUESTS + '/' + item['id']
    assert_denied(client.get(ADMIN_REQUESTS))
    assert_denied(client.patch(path, json={'status': 'closed'}))
    csrf = login(client, account)
    key = make_key(client, csrf)['key']
    for headers in (csrf, {**csrf, 'X-API-Key': key}):
        assert_denied(client.get(ADMIN_REQUESTS, headers=headers))
        assert_denied(client.patch(path, json={'status': 'closed'}, headers=headers))
    assert rows() == [item]


def test_admin_patch_requires_own_csrf_and_matching_origin(saas_env):
    app, admin, client, _ = saas_env
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    item, = rows()
    path = ADMIN_REQUESTS + '/' + item['id']
    with TestClient(app, base_url=PUBLIC) as other:
        foreign_csrf = admin_login(other).json()['session_csrf']
    for csrf in ('', 'wrong', foreign_csrf):
        assert_denied(admin.patch(path, json={'status': 'closed'}, headers={'X-CSRF-Token': csrf}))
        assert rows() == [item]
    for origin in ('https://evil.example', PUBLIC + '.evil.example', PUBLIC + ':444', 'null'):
        assert_denied(admin.get(ADMIN_REQUESTS, headers={'Origin': origin}))
        assert_denied(admin.patch(path, json={'status': 'closed'}, headers={'Origin': origin}))
        assert rows() == [item]
    assert admin.post(AUTH + '/logout').status_code == 200
    assert_denied(admin.get(ADMIN_REQUESTS))
    assert_denied(admin.patch(path, json={'status': 'closed'}))
    assert rows() == [item]


@pytest.mark.parametrize('status', ['active', 'approved', '', None, '<script>private-status</script>'])
def test_admin_rejects_invalid_status_without_mutation(saas_env, status):
    _, admin, client, _ = saas_env
    assert client.post(REQUESTS, json=PAYLOAD).status_code == 200
    before = rows()
    response = admin.patch(ADMIN_REQUESTS + '/' + before[0]['id'], json={'status': status})
    assert response.status_code == 422
    assert 'private-status' not in response.text
    assert all(set(error) <= {'loc', 'msg', 'type'} for error in response.json()['detail'])
    assert rows() == before


def test_admin_unknown_request_is_404(saas_env):
    response = saas_env[1].patch(ADMIN_REQUESTS + '/does-not-exist', json={'status': 'reviewed'})
    assert response.status_code == 404
    assert rows() == []


@pytest.mark.parametrize('mode', ['selfhost', 'desktop'])
def test_web_stream_root_and_studio_in_fresh_process(tmp_path, mode):
    """Optional heavy runtime; route assertions run in Docker/full dependencies."""
    code = r'''
import sys
try:
    from apps import web_stream as ws
except ModuleNotFoundError as error:
    print('OPTIONAL_WEB_STREAM_DEPENDENCY:' + str(error))
    sys.exit(77)
from pathlib import Path
from fastapi.testclient import TestClient
from apps import saas
root = Path(sys.argv[1])
ws.DIST_DIR = root / 'dist'
ws.DIST_DIR.mkdir()
(ws.DIST_DIR / 'index.html').write_text('<html>OWNER-STUDIO-SHELL</html>')
landing = root / 'landing_static'
landing.mkdir()
(landing / 'homepage.html').write_text('<html><link rel="canonical" href="__PUBLIC_URL__/">PUBLIC-HOMEPAGE</html>')
saas.__file__ = str(root / 'saas.py')
mode = sys.argv[2]
with TestClient(ws.app, base_url='https://voice.example.com', client=('127.0.0.1', 1234)) as client:
    response = client.get('/', follow_redirects=False)
    assert response.status_code == 200, response.text
    if mode == 'desktop':
        assert 'OWNER-STUDIO-SHELL' in response.text
        assert 'PUBLIC-HOMEPAGE' not in response.text
        assert client.get('/saas/homepage').status_code == 404
    else:
        assert 'PUBLIC-HOMEPAGE' in response.text
        assert 'https://voice.example.com/' in response.text
        assert 'OWNER-STUDIO-SHELL' not in response.text
        for path in ('/studio', '/studio/'):
            denied = client.get(path, follow_redirects=False)
            assert denied.status_code in (401, 403, 302, 303, 307), denied.text
            assert 'OWNER-STUDIO-SHELL' not in denied.text
            if denied.is_redirect:
                assert '/saas/admin/login' in denied.headers['location']
        saas.init_db()
        saas.bootstrap_admin('homepage-owner', 'homepage-owner-password-123')
        auth = client.post('/saas/api/admin-auth/login', json={'username': 'homepage-owner', 'password': 'homepage-owner-password-123'})
        assert auth.status_code == 200, auth.text
        for path in ('/studio', '/studio/'):
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert 'OWNER-STUDIO-SHELL' in response.text
        assert 'PUBLIC-HOMEPAGE' in client.get('/').text
'''
    env = {**os.environ, 'CIT_DEPLOYMENT_MODE': mode, 'CIT_PUBLIC_URL': PUBLIC,
           'CIT_SAAS_DB': str(tmp_path / 'saas.sqlite3'), 'CIT_SKIP_MODEL_AUTOLOAD': '1',
           'LOCALAPPDATA': str(tmp_path / 'localappdata')}
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), mode],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=60)
    if result.returncode == 77 and 'OPTIONAL_WEB_STREAM_DEPENDENCY:' in result.stdout:
        pytest.skip(result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr

"""SaaS security and accounting regressions; all synthesis and storage are isolated."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

PUBLIC = "https://voice.example.com"
PASSWORD = "test-password-12345"
ADMIN_USERNAME = "owner"
ADMIN_PASSWORD = "owner-password-12345"
ADMIN_HEADERS = {}  # Admin CSRF is installed on the authenticated client.


def assert_denied(response):
    assert response.status_code in (401, 403), response.text


def assert_no_secrets(value, *secrets):
    text = str(value)
    for secret in secrets:
        assert secret not in text
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"password", "password_hash", "key_hash", "token_hash"}
            assert_no_secrets(item, *secrets)
    elif isinstance(value, list):
        for item in value:
            assert_no_secrets(item, *secrets)


def test_admin_requires_session_regardless_of_peer_and_host(saas_env):
    app, admin, _, _ = saas_env
    assert admin.get('/saas/api/admin/users').status_code == 200
    for peer, url, headers in [
        (('127.0.0.1', 1234), 'http://127.0.0.1', {}),
        (('203.0.113.8', 1234), PUBLIC, {}),
        (('203.0.113.8', 1234), 'http://127.0.0.1', {}),
        (('127.0.0.1', 1234), PUBLIC, {}),
        (('127.0.0.1', 1234), 'http://127.0.0.1', {'X-Forwarded-For': '203.0.113.8'}),
        (('127.0.0.1', 1234), 'http://127.0.0.1', {'Forwarded': 'for=203.0.113.8'}),
        (('127.0.0.1', 1234), 'http://127.0.0.1', {'X-Real-IP': '127.0.0.1'}),
        (('127.0.0.1', 1234), 'http://127.0.0.1', {'CF-Connecting-IP': '127.0.0.1'}),
        (('127.0.0.1', 1234), 'http://127.0.0.1', {'X-Forwarded-Host': 'localhost'}),
    ]:
        with TestClient(app, client=peer, base_url=url) as client:
            assert_denied(client.get('/saas/api/admin/users', headers=headers))


def test_admin_mutations_need_csrf_and_matching_origin(saas_env):
    _, admin, _, _ = saas_env
    activate_trial(admin)
    payload = dict(name='Alice', email='alice@example.com', password=PASSWORD,
                   plan_id='trial', status='active')
    assert_denied(admin.post('/saas/api/admin/users', json=payload,
                            headers={'X-CSRF-Token': ''}))
    assert_denied(admin.post('/saas/api/admin/users', json=payload,
                            headers={**ADMIN_HEADERS, 'Origin': 'https://evil.example'}))
    response = admin.post('/saas/api/admin/users', json=payload,
                          headers={**ADMIN_HEADERS, 'Origin': PUBLIC})
    assert response.status_code in (200, 201), response.text
    assert_no_secrets(response.json(), PASSWORD)


def test_registration_disabled_and_weak_admin_password_rejected(saas_env):
    _, admin, client, _ = saas_env
    payload = dict(name='Alice', email='alice@example.com', password='short',
                   plan_id='trial', status='active')
    assert admin.post('/saas/api/admin/users', json=payload,
                      headers=ADMIN_HEADERS).status_code in (400, 422)
    payload['password'] = PASSWORD
    assert client.post('/saas/api/register', json=payload).status_code in (403, 404)


def test_login_cookie_and_session_csrf(saas_env, account):
    _, _, client, _ = saas_env
    response = client.post('/saas/api/login', json={'email': account['email'], 'password': PASSWORD})
    assert response.status_code == 200, response.text
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'path=/saas' in cookie
    assert 'samesite=' in cookie
    csrf = response.json()['session_csrf']
    assert csrf
    assert_no_secrets(response.json(), PASSWORD)
    assert client.get('/saas/api/me').status_code == 200
    for headers in ({}, {'X-CSRF-Token': 'wrong'}, {'X-CSRF-Token': csrf, 'Origin': 'https://evil.example'}):
        assert_denied(client.post('/saas/api/keys', json={'name': 'test'}, headers=headers))
    created = client.post('/saas/api/keys', json={'name': 'test'}, headers={'X-CSRF-Token': csrf})
    assert created.status_code in (200, 201), created.text


def test_wrong_password_and_unknown_account_denied(saas_env, account):
    client = saas_env[2]
    for email, password in [(account['email'], 'incorrect-password-123'), ('absent@example.com', PASSWORD)]:
        assert_denied(client.post('/saas/api/login', json={'email': email, 'password': password}))
    assert_denied(client.get('/saas/api/me'))


def login(client, account):
    response = client.post('/saas/api/login', json={'email': account['email'], 'password': PASSWORD})
    assert response.status_code == 200, response.text
    return {'X-CSRF-Token': response.json()['session_csrf']}


def make_key(client, csrf):
    response = client.post('/saas/api/keys', headers=csrf, json={'name': 'automation'})
    assert response.status_code in (200, 201), response.text
    return {**response.json()['key'], 'key': response.json()['api_key']}


def test_session_generation_requires_csrf(saas_env, account):
    client = saas_env[2]
    csrf = login(client, account)
    assert_denied(client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'hello'}))
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'hello'}, headers=csrf).status_code == 200


def test_personal_key_cannot_enter_admin(saas_env, account):
    app, _, client, _ = saas_env
    key = make_key(client, login(client, account))['key']
    assert key.startswith('sv_')
    with TestClient(app, base_url=PUBLIC, client=('203.0.113.7', 42)) as remote:
        headers = {'X-API-Key': key}
        assert remote.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'hello'}, headers=headers).status_code == 200
        assert_denied(remote.get('/saas/api/admin/users', headers=headers))
        assert_denied(remote.patch('/saas/api/admin/settings', json={'registration_enabled': True},
                                   headers={**headers, **ADMIN_HEADERS}))
    assert_no_secrets(client.get('/saas/api/me').json(), key, PASSWORD)
    assert_no_secrets(client.get('/saas/api/me').json(), key, PASSWORD)


def test_per_job_and_monthly_quota(saas_env, account):
    client = saas_env[2]
    csrf = login(client, account)
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'a' * 501}, headers=csrf).status_code in (400, 403, 422, 429)
    for _ in range(2):
        r = client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'a' * 500}, headers=csrf)
        assert r.status_code == 200, r.text
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'a'}, headers=csrf).status_code in (402, 403, 429)


def test_keys_are_tenant_scoped_and_revocable(saas_env, account):
    app, admin, client, _ = saas_env
    csrf = login(client, account)
    own = make_key(client, csrf)
    other_account = create_account(admin, 'other@example.com')
    with TestClient(app, base_url=PUBLIC, client=('203.0.113.9', 1234)) as other:
        other_csrf = login(other, other_account)
        other_key = make_key(other, other_csrf)
        listing = client.get('/saas/api/me')
        assert listing.status_code == 200
        assert other_key['id'] not in [key['id'] for key in listing.json()['api_keys']]
        response = client.delete('/saas/api/keys/' + str(other_key['id']), headers=csrf)
        assert response.status_code in (403, 404)
        other.cookies.clear()
        assert other.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'still works'},
                          headers={'X-API-Key': other_key['key']}).status_code == 200
    assert client.delete('/saas/api/keys/' + str(own['id']), headers=csrf).status_code in (200, 204)
    client.cookies.clear()
    assert_denied(client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'revoked'},
                              headers={'X-API-Key': own['key']}))


def test_user_cannot_read_or_patch_admin(saas_env, account):
    client = saas_env[2]
    csrf = login(client, account)
    for resource in ('users', 'plans', 'settings'):
        assert_denied(client.get('/saas/api/admin/' + resource))
        assert_denied(client.patch('/saas/api/admin/' + (resource if resource == 'settings' else resource + '/trial'),
                                   headers={**csrf, **ADMIN_HEADERS}, json={'registration_enabled': False} if resource == 'settings' else {}))


def test_synthesis_failure_refunds_reserved_quota(saas_env, account):
    _, _, client, synth = saas_env
    csrf = login(client, account)
    synth['mode'] = 'http_error'
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'a' * 500}, headers=csrf).status_code >= 400
    synth['mode'] = 'exception'
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'b' * 500}, headers=csrf).status_code >= 400
    synth['mode'] = 'ok'
    for _ in range(2):
        response = client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'c' * 500}, headers=csrf)
        assert response.status_code == 200, response.text
    assert client.post('/saas/api/tts/generate', json={'voice_id': 'public-voice', 'text': 'd'}, headers=csrf).status_code in (402, 403, 429)


@pytest.fixture
def saas_env(tmp_path, monkeypatch):
    from apps import saas, remote_access

    monkeypatch.setenv('CIT_DEPLOYMENT_MODE', 'selfhost')
    monkeypatch.setenv('CIT_PUBLIC_URL', PUBLIC)
    monkeypatch.setenv('CIT_SAAS_DB', str(tmp_path / 'saas.sqlite3'))
    state = {'mode': 'ok', 'calls': []}

    def synth(payload):
        state['calls'].append(payload)
        if state['mode'] == 'http_error':
            return Response('unavailable', status_code=503)
        if state['mode'] == 'exception':
            raise RuntimeError('private engine traceback')
        return Response(b'RIFFfake-wave', media_type='audio/wav')

    monkeypatch.setattr(saas, 'generate_audio', synth)
    monkeypatch.setattr(saas, 'list_voices', lambda: [
        {'id': 'public-voice', 'name': 'Public'},
        {'id': 'owner-clone', 'name': 'Secret clone', 'isCloned': True},
    ])
    saas.init_db()
    saas.bootstrap_admin(ADMIN_USERNAME, ADMIN_PASSWORD)
    app = FastAPI()
    app.add_middleware(remote_access.RemoteAccessMiddleware)
    app.include_router(saas.router)
    with TestClient(app, base_url=PUBLIC, client=('203.0.113.20', 1234)) as admin:
        response = admin.post('/saas/api/admin-auth/login', json={
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        })
        assert response.status_code == 200, response.text
        admin.headers.update({'X-CSRF-Token': response.json()['session_csrf']})
        with TestClient(app, base_url=PUBLIC, client=('203.0.113.10', 1234)) as client:
            yield app, admin, client, state


def activate_trial(admin):
    response = admin.patch('/saas/api/admin/plans/trial', headers=ADMIN_HEADERS, json={
        'is_draft': False, 'enabled': True, 'price_minor': 0,
        'char_limit': 1000, 'job_max_chars': 500, 'max_api_keys': 2,
    })
    assert response.status_code == 200, response.text


def create_account(admin, email='alice@example.com', plan_id='trial'):
    response = admin.post('/saas/api/admin/users', headers=ADMIN_HEADERS, json={
        'name': email.split('@')[0], 'email': email, 'password': PASSWORD,
        'plan_id': plan_id, 'status': 'active',
    })
    assert response.status_code == 201, response.text
    return response.json()['user']


@pytest.fixture
def account(saas_env):
    activate_trial(saas_env[1])
    return create_account(saas_env[1])


def test_defaults_draft_plans_and_signup_cannot_be_opened(saas_env):
    _, admin, client, _ = saas_env
    plans = admin.get('/saas/api/admin/plans').json()['items']
    assert {p['id'] for p in plans} == {'trial', 'pro', 'business'}
    assert all(p['is_draft'] and not p['enabled'] for p in plans)
    assert client.get('/saas/api/config').json()['registration_enabled'] is False
    assert admin.patch('/saas/api/admin/settings', headers=ADMIN_HEADERS,
                       json={'registration_enabled': True}).status_code == 403
    for plan in plans:
        response = admin.post('/saas/api/admin/users', headers=ADMIN_HEADERS, json={
            'name': 'Draft', 'email': 'draft@example.com', 'password': PASSWORD,
            'plan_id': plan['id'], 'status': 'active',
        })
        assert response.status_code == 403
    assert admin.get('/saas/api/admin/users').json()['items'] == []


def test_signup_only_after_explicit_activation(saas_env):
    _, admin, client, _ = saas_env
    activate_trial(admin)
    response = admin.patch('/saas/api/admin/settings', headers=ADMIN_HEADERS,
                           json={'registration_enabled': True})
    assert response.status_code == 200
    assert admin.get('/saas/api/admin/settings').json()['registration_enabled'] is True
    payload = {'email': 'signup@example.com', 'name': 'Signup', 'password': PASSWORD}
    assert_denied(client.post('/saas/api/register', json=payload, headers={'Origin': 'https://evil.example'}))
    response = client.post('/saas/api/register', json=payload, headers={'Origin': PUBLIC})
    assert response.status_code == 201, response.text
    assert response.json()['user']['plan_id'] == 'trial'
    assert client.get('/saas/api/me').status_code == 200
    assert_no_secrets(admin.get('/saas/api/admin/users').json(), PASSWORD)


@pytest.mark.parametrize('patch', [
    {'enabled': True},
    {'is_draft': False, 'enabled': True, 'price_minor': None},
    {'is_draft': False, 'enabled': True, 'price_minor': 0, 'char_limit': 0},
    {'is_draft': False, 'enabled': True, 'price_minor': 0, 'char_limit': 10, 'job_max_chars': 11},
    {'char_limit': -1},
])
def test_invalid_plan_activation_is_atomic(saas_env, patch):
    admin = saas_env[1]
    before = admin.get('/saas/api/admin/plans').json()
    response = admin.patch('/saas/api/admin/plans/pro', json=patch, headers=ADMIN_HEADERS)
    assert response.status_code == 422, response.text
    assert admin.get('/saas/api/admin/plans').json() == before


def test_draft_assignment_rejected_without_changing_user(saas_env, account):
    admin = saas_env[1]
    for pid in ('pro', 'business'):
        response = admin.patch('/saas/api/admin/users/' + account['id'],
                               headers=ADMIN_HEADERS, json={'plan_id': pid})
        assert response.status_code == 403
    assert admin.get('/saas/api/admin/users').json()['items'][0]['plan_id'] == 'trial'


@pytest.mark.parametrize('patch', [
    {'status': 'suspended'},
    {'plan_expires_at': '2000-01-01T00:00:00+00:00'},
])
def test_suspension_and_expiry_revoke_existing_session_and_key(saas_env, account, patch):
    app, admin, client, synth = saas_env
    csrf = login(client, account)
    key = make_key(client, csrf)['key']
    response = admin.patch('/saas/api/admin/users/' + account['id'], headers=ADMIN_HEADERS, json=patch)
    assert response.status_code == 200, response.text
    assert_denied(client.get('/saas/api/me'))
    assert_denied(client.post('/saas/api/tts/generate', headers=csrf,
                              json={'voice_id': 'public-voice', 'text': 'blocked'}))
    with TestClient(app, base_url=PUBLIC) as api:
        assert_denied(api.post('/saas/api/tts/generate', headers={'X-API-Key': key},
                               json={'voice_id': 'public-voice', 'text': 'blocked'}))
    assert_denied(client.post('/saas/api/login', json={'email': account['email'], 'password': PASSWORD}))
    assert not synth['calls']


def test_key_limit_password_and_tokens_not_stored_in_plaintext(saas_env, account):
    from apps import saas

    _, admin, client, _ = saas_env
    csrf = login(client, account)
    keys = [make_key(client, csrf)['key'] for _ in range(2)]
    assert client.post('/saas/api/keys', headers=csrf, json={'name': 'third'}).status_code == 409
    session = client.cookies.get('__Secure-cit_saas')
    with sqlite3.connect(saas.db_path()) as db:
        dump = '\n'.join(db.iterdump())
    assert_no_secrets(dump, PASSWORD, session, *keys)
    assert_no_secrets(admin.get('/saas/api/admin/users').json(), PASSWORD, session, *keys)
    assert_no_secrets(client.get('/saas/api/me').json(), PASSWORD, session, *keys)


def test_clone_and_unknown_voice_never_reach_synth(saas_env, account):
    _, _, client, synth = saas_env
    csrf = login(client, account)
    voices = client.get('/saas/api/voices')
    assert voices.status_code == 200
    assert [voice['id'] for voice in voices.json()] == ['public-voice']
    for voice in ('owner-clone', 'missing'):
        assert client.post('/saas/api/tts/generate', headers=csrf,
                           json={'voice_id': voice, 'text': 'hello'}).status_code == 422
    assert not synth['calls']
    assert client.get('/saas/api/me').json()['usage']['used'] == 0


def test_concurrent_reservations_and_finish_are_atomic(saas_env, account):
    from apps import saas
    import threading

    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait(timeout=5)
        try:
            return saas.reserve(account['id'], 'a' * 500)
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    ids = [value for value in outcomes if isinstance(value, str)]
    assert len(ids) == 1, outcomes
    assert 429 in outcomes
    client = saas_env[2]
    login(client, account)
    usage = client.get('/saas/api/me').json()['usage']
    assert (usage['used'], usage['reserved'], usage['remaining']) == (0, 500, 500)
    saas.finish(ids[0], True)
    saas.finish(ids[0], True)
    saas.finish(ids[0], False, 'late failure must not refund completed job')
    usage = client.get('/saas/api/me').json()['usage']
    assert (usage['used'], usage['reserved'], usage['remaining']) == (500, 0, 500)
    second = saas.reserve(account['id'], 'b' * 500)
    saas.finish(second, True)
    with pytest.raises(HTTPException) as error:
        saas.reserve(account['id'], 'c')
    assert error.value.status_code == 402


def test_quota_ledger_and_balances_are_tenant_isolated(saas_env, account):
    app, admin, client, _ = saas_env
    csrf = login(client, account)
    response = client.post('/saas/api/tts/generate', headers=csrf,
                           json={'voice_id': 'public-voice', 'text': 'a' * 500})
    assert response.status_code == 200
    job_id = response.headers['x-usage-job']
    other_account = create_account(admin, 'other@example.com')
    with TestClient(app, base_url=PUBLIC) as other:
        other_csrf = login(other, other_account)
        assert other.get('/saas/api/usage').json()['items'] == []
        assert other.get('/saas/api/me').json()['usage']['remaining'] == 1000
        response = other.post('/saas/api/tts/generate', headers=other_csrf,
                              json={'voice_id': 'public-voice', 'text': 'b' * 100})
        assert response.status_code == 200
        other_job = response.headers['x-usage-job']
        assert [j['id'] for j in other.get('/saas/api/usage').json()['items']] == [other_job]
    assert [j['id'] for j in client.get('/saas/api/usage').json()['items']] == [job_id]
    assert client.get('/saas/api/me').json()['usage']['remaining'] == 500


def test_db_path_env_and_initialization_are_isolated_and_idempotent(saas_env, tmp_path, monkeypatch):
    from apps import saas

    assert saas.db_path() == tmp_path / 'saas.sqlite3'
    saas.init_db()
    assert len(saas_env[1].get('/saas/api/admin/plans').json()['items']) == 3
    monkeypatch.delenv('CIT_SAAS_DB')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'localappdata'))
    expected = tmp_path / 'localappdata' / 'CitVoiceStudio' / 'saas.sqlite3'
    assert saas.db_path() == expected
    saas.init_db()
    assert expected.exists()


def test_logout_csrf_and_expired_session(saas_env, account):
    from apps import saas

    client = saas_env[2]
    csrf = login(client, account)
    assert_denied(client.post('/saas/api/logout'))
    assert client.get('/saas/api/me').status_code == 200
    assert client.post('/saas/api/logout', headers=csrf).status_code == 200
    assert_denied(client.get('/saas/api/me'))
    login(client, account)
    with saas.connect() as db:
        db.execute('UPDATE sessions SET expires_at=0')
    assert_denied(client.get('/saas/api/me'))


def test_user_read_origin_and_key_write_origin_are_checked(saas_env, account):
    app, _, client, _ = saas_env
    key = make_key(client, login(client, account))['key']
    assert_denied(client.get('/saas/api/me', headers={'Origin': 'https://evil.example'}))
    with TestClient(app, base_url=PUBLIC) as api:
        assert_denied(api.post('/saas/api/tts/generate',
                               headers={'X-API-Key': key, 'Origin': 'https://evil.example'},
                               json={'voice_id': 'public-voice', 'text': 'forbidden'}))


def test_nfc_normalized_characters_and_recovery_refund(saas_env, account):
    from apps import saas

    client = saas_env[2]
    login(client, account)
    job = saas.reserve(account['id'], '  e\u0301  ')
    assert client.get('/saas/api/me').json()['usage']['reserved'] == 1
    saas.recover_jobs()
    assert client.get('/saas/api/me').json()['usage']['remaining'] == 1000
    # Finishing a recovered reservation cannot retroactively charge it.
    saas.finish(job, True)
    assert client.get('/saas/api/me').json()['usage']['used'] == 0


def test_plan_decrease_preserves_usage_and_blocks_new_charges(saas_env, account):
    _, admin, client, _ = saas_env
    csrf = login(client, account)
    assert client.post('/saas/api/tts/generate', headers=csrf,
                       json={'voice_id': 'public-voice', 'text': 'a' * 500}).status_code == 200
    response = admin.patch('/saas/api/admin/plans/trial', headers=ADMIN_HEADERS,
                           json={'char_limit': 400, 'job_max_chars': 400})
    assert response.status_code == 200, response.text
    usage = client.get('/saas/api/me').json()['usage']
    assert (usage['used'], usage['limit'], usage['remaining']) == (500, 400, 0)
    assert client.post('/saas/api/tts/generate', headers=csrf,
                       json={'voice_id': 'public-voice', 'text': 'x'}).status_code == 402
    # Increasing the same plan releases headroom without erasing the ledger.
    assert admin.patch('/saas/api/admin/plans/trial', headers=ADMIN_HEADERS,
                       json={'char_limit': 1000}).status_code == 200
    usage = client.get('/saas/api/me').json()['usage']
    assert (usage['used'], usage['remaining']) == (500, 500)


def test_global_reservation_survives_requests_and_refunds_on_explicit_recovery(saas_env, account):
    from apps import saas

    _, admin, client, synth = saas_env
    login(client, account)
    other = create_account(admin, 'other@example.com')
    job = saas.reserve(account['id'], 'a' * 500)
    # init_db is called by every route and must never recover an active job.
    assert client.get('/saas/api/config').status_code == 200
    assert admin.get('/saas/api/admin/users').status_code == 200
    assert client.get('/saas/api/me').json()['usage']['reserved'] == 500
    with pytest.raises(HTTPException) as error:
        saas.reserve(other['id'], 'x')
    assert error.value.status_code == 429
    assert not synth['calls']
    saas.recover_jobs()
    saas.recover_jobs()
    assert client.get('/saas/api/me').json()['usage']['remaining'] == 1000
    with saas.connect() as db:
        row = db.execute('SELECT status FROM usage_jobs WHERE id=?', (job,)).fetchone()
        assert row['status'] == 'failed'
    other_job = saas.reserve(other['id'], 'x')
    saas.finish(other_job, False)


@pytest.mark.parametrize('path', ['/saas/api/login', '/saas/api/register', '/saas/api/admin/users'])
def test_validation_errors_never_echo_passwords(saas_env, path):
    client = saas_env[1] if '/admin/' in path else saas_env[2]
    secret = 'tiny-secret'
    response = client.post(path, headers=ADMIN_HEADERS, json={
        'email': 'invalid@example.com', 'password': secret,
        'name': 'Invalid', 'plan_id': 'trial', 'status': 'active',
    })
    assert response.status_code == 422
    assert secret not in response.text
    for error in response.json()['detail']:
        assert set(error) <= {'loc', 'msg', 'type'}


def test_reserve_rechecks_suspension_after_authentication(saas_env, account):
    from apps import saas

    admin = saas_env[1]
    # A status change between authentication and reservation must still stop work.
    assert admin.patch('/saas/api/admin/users/' + account['id'], headers=ADMIN_HEADERS,
                       json={'status': 'suspended'}).status_code == 200
    with pytest.raises(HTTPException) as error:
        saas.reserve(account['id'], 'hello')
    assert error.value.status_code == 403
    with saas.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM usage_jobs').fetchone()[0] == 0


def test_busy_server_rejects_other_tenant_request_without_charge(saas_env, account):
    from apps import saas

    _, admin, client, synth = saas_env
    other = create_account(admin, 'occupier@example.com')
    job = saas.reserve(other['id'], 'held reservation')
    csrf = login(client, account)
    response = client.post('/saas/api/tts/generate', headers=csrf,
                           json={'voice_id': 'public-voice', 'text': 'hello'})
    assert response.status_code == 429
    assert not synth['calls']
    assert client.get('/saas/api/me').json()['usage']['used'] == 0
    assert client.get('/saas/api/usage').json()['items'] == []
    saas.finish(job, False)
    assert client.post('/saas/api/tts/generate', headers=csrf,
                       json={'voice_id': 'public-voice', 'text': 'hello'}).status_code == 200


def test_forwarded_admin_mutation_denied_even_with_personal_key(saas_env, account):
    _, _, client, _ = saas_env
    key = make_key(client, login(client, account))['key']
    for header in ('X-Forwarded-For', 'Forwarded', 'X-Forwarded-Host', 'X-Real-IP', 'CF-Connecting-IP'):
        response = client.patch('/saas/api/admin/users/' + account['id'],
                                headers={**ADMIN_HEADERS, 'X-API-Key': key, header: '127.0.0.1'},
                                json={'status': 'suspended'})
        assert_denied(response)
    assert client.get('/saas/api/me').json()['user']['status'] == 'active'

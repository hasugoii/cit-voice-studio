"""Admin authentication regressions using real credentials and persisted sessions."""
import hashlib
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from test_saas import (
    ADMIN_PASSWORD, ADMIN_USERNAME, PASSWORD, PUBLIC, account, assert_denied,
    assert_no_secrets, login, make_key, saas_env,
)

AUTH = '/saas/api/admin-auth'
COOKIE = '__Secure-cit_admin'


def test_password_rotation_during_login_cannot_create_stale_session(saas_env,monkeypatch):
    from apps import saas
    _,_,client,_=saas_env
    verify=saas._password_ok
    rotated=saas._password_hash('rotated-during-login-123')
    def rotate_after_verify(password,stored):
        result=verify(password,stored)
        with saas.connect() as db:
            db.execute('UPDATE admin_users SET password_hash=?',(rotated,))
            db.execute('DELETE FROM admin_sessions')
        return result
    monkeypatch.setattr(saas,'_password_ok',rotate_after_verify)
    response=client.post(AUTH+'/login',json={'username':ADMIN_USERNAME,'password':ADMIN_PASSWORD})
    assert response.status_code==401
    with saas.connect() as db:assert db.execute('SELECT COUNT(*) FROM admin_sessions').fetchone()[0]==0


def test_trusted_cli_reset_revokes_sessions_without_printing_secret(saas_env,monkeypatch,capsys):
    import io
    import json
    import sys
    from apps import admin_cli
    _,admin,client,_=saas_env
    fresh='fresh-cli-admin-password-123'
    monkeypatch.setattr(sys,'argv',['admin_cli','reset-password','--stdin-json'])
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps({'username':ADMIN_USERNAME,'password':fresh})))
    admin_cli.main()
    assert fresh not in capsys.readouterr().out
    assert admin.get(AUTH+'/me').status_code==401
    admin_login(client,fresh)


def admin_login(client, password=ADMIN_PASSWORD):
    response = client.post(AUTH + '/login', json={
        'username': ADMIN_USERNAME, 'password': password,
    })
    assert response.status_code == 200, response.text
    assert response.json()['session_csrf']
    return response


def test_admin_cookie_lifetime_and_hashed_storage(saas_env):
    from apps import saas

    app, _, _, _ = saas_env
    before = time.time()
    with TestClient(app, base_url=PUBLIC) as client:
        response = admin_login(client)
        token = client.cookies.get(COOKIE)
        assert token
        cookie = response.headers['set-cookie'].lower()
        for attribute in ('secure', 'httponly', 'samesite=strict', 'path=/', 'max-age=43200'):
            assert attribute in cookie
        assert 'path=/saas' not in cookie
        with saas.connect() as db:
            row = db.execute('SELECT * FROM admin_sessions WHERE token_hash=?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            assert row is not None
            assert before + 43200 <= row['expires_at'] <= time.time() + 43200
            assert row['csrf'] == response.json()['session_csrf']
            owner = db.execute('SELECT * FROM admin_users WHERE id=?', (row['admin_id'],)).fetchone()
            assert owner['username'] == ADMIN_USERNAME
            assert owner['name'] == 'Quản trị viên'
            assert owner['password_hash'] != ADMIN_PASSWORD
            dump = '\n'.join(db.iterdump())
        assert_no_secrets(dump, token, ADMIN_PASSWORD)
        me = client.get(AUTH + '/me')
        assert me.status_code == 200, me.text
        assert me.json()['session_csrf'] == response.json()['session_csrf']
        assert_no_secrets(me.json(), token, ADMIN_PASSWORD)
        assert client.get('/saas/api/admin/users').status_code == 200


def test_first_admin_bootstrap_is_one_time_even_when_suspended(saas_env):
    from apps import saas

    with saas.connect() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM admin_users')]
    assert len(before) == 1
    for username in (ADMIN_USERNAME, 'another-owner'):
        with pytest.raises(HTTPException) as error:
            saas.bootstrap_admin(username, 'another-password-12345')
        assert error.value.status_code == 409
    with saas.connect() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM admin_users')] == before
        db.execute("UPDATE admin_users SET status='suspended'")
    with pytest.raises(HTTPException) as error:
        saas.bootstrap_admin('replacement', ADMIN_PASSWORD)
    assert error.value.status_code == 409
    assert_denied(saas_env[1].get(AUTH + '/me'))
    assert_denied(saas_env[1].get('/saas/api/admin/users'))


@pytest.mark.parametrize('path', [AUTH + '/bootstrap', '/saas/api/bootstrap-admin', '/saas/api/admin/bootstrap'])
def test_no_public_admin_bootstrap(saas_env, path):
    from apps import saas

    # Also check an empty installation: first-owner creation must stay offline.
    with saas.connect() as db:
        db.execute('DELETE FROM admin_sessions')
        db.execute('DELETE FROM admin_users')
    response = saas_env[2].post(path, json={'username': 'attacker', 'password': ADMIN_PASSWORD})
    assert response.status_code in (404, 405)
    with saas.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0] == 0


@pytest.mark.parametrize('origin', ['https://evil.example', PUBLIC + '.evil.example', PUBLIC + ':444', 'null'])
def test_admin_origin_must_match_configured_origin(saas_env, origin):
    _, admin, client, _ = saas_env
    assert_denied(client.post(AUTH + '/login', headers={'Origin': origin},
                             json={'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD}))
    assert_denied(admin.get(AUTH + '/me', headers={'Origin': origin}))
    assert_denied(admin.get('/saas/api/admin/users', headers={'Origin': origin}))
    assert_denied(admin.patch('/saas/api/admin/settings', headers={'Origin': origin},
                             json={'registration_enabled': False}))
    assert admin.get(AUTH + '/me', headers={'Origin': PUBLIC}).status_code == 200


def test_logout_requires_csrf_and_revokes_replayed_token(saas_env):
    app, admin, _, _ = saas_env
    token = admin.cookies.get(COOKIE)
    for csrf in ('', 'wrong'):
        assert_denied(admin.post(AUTH + '/logout', headers={'X-CSRF-Token': csrf}))
        assert admin.get(AUTH + '/me').status_code == 200
    assert admin.post(AUTH + '/logout').status_code == 200
    assert admin.cookies.get(COOKIE) is None
    assert_denied(admin.get(AUTH + '/me'))
    with TestClient(app, base_url=PUBLIC) as replay:
        replay.cookies.set(COOKIE, token)
        assert_denied(replay.get('/saas/api/admin/users'))


def test_expired_admin_session_is_denied(saas_env):
    from apps import saas

    admin = saas_env[1]
    with saas.connect() as db:
        db.execute('UPDATE admin_sessions SET expires_at=?', (time.time() - 1,))
    assert_denied(admin.get(AUTH + '/me'))
    assert_denied(admin.get('/saas/api/admin/users'))
    assert_denied(admin.patch('/saas/api/admin/settings', json={'registration_enabled': False}))


def test_csrf_is_bound_to_admin_session(saas_env):
    app, admin, _, _ = saas_env
    with TestClient(app, base_url=PUBLIC) as other:
        csrf = admin_login(other).json()['session_csrf']
        assert csrf != admin.headers['X-CSRF-Token']
        assert_denied(admin.post(AUTH + '/logout', headers={'X-CSRF-Token': csrf}))
        assert_denied(admin.patch('/saas/api/admin/settings', headers={'X-CSRF-Token': csrf},
                                  json={'registration_enabled': False}))
    assert admin.get(AUTH + '/me').status_code == 200


def test_login_rotates_attacker_supplied_session(saas_env):
    app = saas_env[0]
    fixed = 'attacker-chosen-session-token'
    with TestClient(app, base_url=PUBLIC) as client:
        response = client.post(AUTH + '/login', headers={'Cookie': COOKIE + '=' + fixed},
                               json={'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD})
        assert response.status_code == 200, response.text
        first = client.cookies.get(COOKIE)
        assert first and first != fixed
        admin_login(client)
        assert client.cookies.get(COOKIE) != first
    with TestClient(app, base_url=PUBLIC) as attacker:
        attacker.cookies.set(COOKIE, fixed)
        assert_denied(attacker.get(AUTH + '/me'))


def test_password_change_requires_current_password_and_revokes_all_sessions(saas_env):
    app, admin, _, _ = saas_env
    changed = 'changed-owner-password-67890'
    with TestClient(app, base_url=PUBLIC) as other:
        admin_login(other)
        payload = {'current_password': ADMIN_PASSWORD, 'new_password': changed}
        for csrf in ('', 'wrong'):
            assert_denied(admin.post(AUTH + '/password', headers={'X-CSRF-Token': csrf}, json=payload))
        assert_denied(admin.post(AUTH + '/password', json={**payload, 'current_password': 'incorrect-password'}))
        assert admin.post(AUTH + '/password', json={**payload, 'new_password': 'short'}).status_code in (400, 422)
        assert admin.get(AUTH + '/me').status_code == 200
        assert other.get(AUTH + '/me').status_code == 200
        response = admin.post(AUTH + '/password', json=payload)
        assert response.status_code == 200, response.text
        assert_no_secrets(response.json(), changed, ADMIN_PASSWORD)
        for client in (admin, other):
            assert_denied(client.get(AUTH + '/me'))
            assert_denied(client.get('/saas/api/admin/users'))
        assert_denied(other.post(AUTH + '/login', json={'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD}))
        admin_login(other, changed)
        assert other.get('/saas/api/admin/users').status_code == 200


def test_bad_credentials_and_attempt_throttling(saas_env):
    client = saas_env[2]
    assert_denied(client.post(AUTH + '/login', json={'username': 'absent', 'password': ADMIN_PASSWORD}))
    statuses = []
    for _ in range(25):
        response = client.post(AUTH + '/login', json={'username': ADMIN_USERNAME, 'password': 'incorrect-password-12345'})
        statuses.append(response.status_code)
        assert response.status_code in (401, 403, 429), response.text
        if response.status_code == 429:
            break
    assert 429 in statuses, statuses
    assert client.post(AUTH + '/login', json={'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD}).status_code == 429
    assert_denied(client.get(AUTH + '/me'))
    assert client.cookies.get(COOKIE) is None


def test_customer_session_and_api_key_cannot_be_elevated(saas_env, account):
    _, _, client, _ = saas_env
    csrf = login(client, account)
    key = make_key(client, csrf)['key']
    headers = {**csrf, 'X-API-Key': key, 'X-Requested-With': 'CIT-SaaS'}
    for path in (AUTH + '/me', '/saas/api/admin/users'):
        assert_denied(client.get(path, headers=headers))
    assert_denied(client.post(AUTH + '/password', headers=headers,
                             json={'current_password': PASSWORD, 'new_password': ADMIN_PASSWORD}))
    assert_denied(client.post(AUTH + '/login', json={'username': account['email'], 'password': PASSWORD}))
    assert client.get('/saas/api/me').status_code == 200


def test_admin_check_and_login_redirect(saas_env):
    _, admin, client, _ = saas_env
    assert_denied(client.get(AUTH + '/check'))
    assert_denied(client.get('/saas/api/admin/users', auth=(ADMIN_USERNAME, ADMIN_PASSWORD)))
    redirect = client.get('/saas/admin', follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers['location'] == '/saas/admin/login'
    assert client.get('/saas/admin/login').status_code == 200
    check = admin.get(AUTH + '/check')
    assert check.status_code == 204
    assert not check.content
    assert check.headers['cache-control'] == 'no-store'
    assert admin.get('/saas/admin', follow_redirects=False).status_code == 200
    assert 'X-Requested-With' not in admin.headers
    assert admin.patch('/saas/api/admin/settings',
                       json={'registration_enabled': False}).status_code == 200


@pytest.mark.parametrize('path,payload', [
    (AUTH + '/login', {'username': ADMIN_USERNAME, 'password': 'x' * 257}),
    (AUTH + '/password', {'current_password': ADMIN_PASSWORD, 'new_password': 'tiny-secret'}),
])
def test_admin_validation_does_not_echo_passwords(saas_env, path, payload):
    response = saas_env[1].post(path, json=payload)
    assert response.status_code == 422
    for name in ('password', 'current_password', 'new_password'):
        if name in payload:
            assert payload[name] not in response.text
    for error in response.json()['detail']:
        assert set(error) <= {'loc', 'msg', 'type'}

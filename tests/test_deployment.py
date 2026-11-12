import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps import deployment, remote_access, server_settings


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    monkeypatch.setenv("CIT_DEPLOYMENT_MODE", "selfhost")
    monkeypatch.setenv("CIT_PUBLIC_URL", "https://voice.example.com/")
    monkeypatch.delenv("CIT_PUBLIC_API_PREFIX", raising=False)
    monkeypatch.setattr(remote_access, "config_path", lambda: tmp_path / "remote.json")
    monkeypatch.setattr(server_settings, "settings_path", lambda: tmp_path / "port.json")
    remote_access.reset_cache()
    app = FastAPI()
    app.include_router(remote_access.router)
    app.include_router(server_settings.router)
    app.add_middleware(remote_access.RemoteAccessMiddleware)
    with TestClient(app, client=("127.0.0.1", 1234), base_url="http://127.0.0.1:8001") as client:
        yield client
    remote_access.reset_cache()


def test_public_domain_not_docker_address(hosted):
    data = hosted.get('/api/remote-access').json()
    assert data['public_url'] == 'https://voice.example.com'
    assert data['public_api_url'] == 'https://voice.example.com/public-api'
    assert data['addresses'] == [] and data['primary_address'] is None
    assert data['port_managed'] is True


def test_selfhost_toggle_no_listener_restart(hosted):
    assert remote_access.listen_host() == '127.0.0.1'
    for enabled in (True, False, True):
        data = hosted.put('/api/remote-access',json={'enabled': enabled}).json()
        assert data['enabled'] is enabled and data['restart_required'] is False
        assert remote_access.listen_host() == '127.0.0.1'


def test_selfhost_port_is_container_managed(hosted, monkeypatch):
    monkeypatch.setenv('PORT','8001')
    server_settings.settings_path().write_text('{"PORT": 9999}')
    assert server_settings.configured_port() == 8001
    assert hosted.put('/api/settings/server-port',json={'port':9000}).status_code == 409
    assert server_settings.configured_port() == 8001


@pytest.mark.parametrize('origin',['http://example.com','https://user:password@example.com','https://example.com/path','https://example.com?x=1','https://example.com#frag','https://example.com:99999',''])
def test_invalid_origin_fails_closed(hosted,monkeypatch,origin):
    monkeypatch.setenv('CIT_PUBLIC_URL',origin)
    with pytest.raises(ValueError): deployment.public_url()


def test_host_header_cannot_override_public_origin(hosted):
    response=hosted.get('/api/deployment',headers={'Host':'evil.example'})
    assert response.status_code == 403
    assert deployment.info()['public_url'] == 'https://voice.example.com'


def test_custom_prefix_and_invalid_prefix(hosted,monkeypatch):
    monkeypatch.setenv('CIT_PUBLIC_API_PREFIX','/voice-api')
    assert deployment.info()['public_api_url'].endswith('/voice-api')
    monkeypatch.setenv('CIT_PUBLIC_API_PREFIX','/../admin')
    with pytest.raises(ValueError): deployment.info()


def test_desktop_default(monkeypatch):
    monkeypatch.delenv('CIT_DEPLOYMENT_MODE',raising=False)
    assert deployment.info()['mode'] == 'desktop'
    assert deployment.public_url() is None


def test_selfhost_swagger_in_fresh_process():
    import os
    import subprocess
    import sys
    code = '''
from apps.web_stream import app
from apps import remote_access
from fastapi.testclient import TestClient
schema = app.openapi()
assert schema['servers'] == [{'url':'https://voice.example.com/public-api'}]
for path in remote_access.PUBLIC_PATHS:
    for operation in schema['paths'][path].values():
        assert operation['security'] == [{'ApiKey': []}]
client = TestClient(app, base_url='http://127.0.0.1:8001', client=('127.0.0.1',1234))
response = client.get('/docs')
assert response.status_code == 200
assert 'https://voice.example.com/public-api/openapi.json' in response.text
response = client.get('/cit-voice-studio.md')
assert response.status_code == 200
assert 'Base URL: https://voice.example.com/public-api' in response.text
'''
    env = {**os.environ, 'CIT_DEPLOYMENT_MODE':'selfhost', 'CIT_PUBLIC_URL':'https://voice.example.com', 'CIT_PUBLIC_API_PREFIX':'/public-api'}
    subprocess.run([sys.executable, '-c', code], env=env,check=True,capture_output=True,timeout=60)

"""Tests for integrations auth_handlers.

Covers stateless auth builders and OAuth2 token fetch/refresh,
including non-standard providers (e.g. SoilScout) that use
alternative JSON field names.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
from unittest.mock import MagicMock, patch

import pytest

from apps.integrations.auth_handlers import (
    AuthError,
    _do_token_request,
    _refresh_token,
    get_auth_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_provider(auth_type):
    """Return a minimal mock provider with the given auth_type."""
    p = MagicMock()
    p.auth_type = auth_type
    return p


def mock_token_response(payload, status_code=200):
    """Return a mock requests.Response for a token endpoint."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.status_code = status_code
    return resp


# ---------------------------------------------------------------------------
# Stateless auth builders
# ---------------------------------------------------------------------------

class TestStatelessAuth:

    def test_api_key_header(self):
        provider = make_provider('api_key_header')
        headers, params, cache = get_auth_session(
            provider, {'X-API-Key': 'abc123'}, {},
        )
        assert headers == {'X-API-Key': 'abc123'}
        assert params == {}
        assert cache is None

    def test_api_key_query(self):
        provider = make_provider('api_key_query')
        headers, params, cache = get_auth_session(
            provider, {'api_key': 'abc123'}, {},
        )
        assert headers == {}
        assert params == {'api_key': 'abc123'}
        assert cache is None

    def test_bearer_token(self):
        provider = make_provider('bearer_token')
        headers, params, cache = get_auth_session(
            provider, {'token': 'mytoken'}, {},
        )
        assert headers == {'Authorization': 'Bearer mytoken'}
        assert cache is None

    def test_basic_auth(self):
        import base64
        provider = make_provider('basic_auth')
        headers, params, cache = get_auth_session(
            provider, {'username': 'user', 'password': 'pass'}, {},
        )
        expected = base64.b64encode(b'user:pass').decode()
        assert headers == {'Authorization': f'Basic {expected}'}
        assert cache is None

    def test_unknown_auth_type_raises(self):
        provider = make_provider('magic_auth')
        with pytest.raises(AuthError, match='Unknown auth_type'):
            get_auth_session(provider, {}, {})


# ---------------------------------------------------------------------------
# _do_token_request — field name normalisation
# ---------------------------------------------------------------------------

class TestDoTokenRequest:

    def test_standard_oauth2_field_names(self):
        """Standard access_token / refresh_token field names are accepted."""
        payload = {
            'access_token': 'acc123',
            'refresh_token': 'ref456',
            'expires_in': 3600,
        }
        with patch('apps.integrations.auth_handlers.requests.post',
                   return_value=mock_token_response(payload)):
            result = _do_token_request('https://example.com/token', {}, 1000.0)

        assert result['access_token'] == 'acc123'
        assert result['refresh_token'] == 'ref456'
        assert result['expires_at'] == 4600.0

    def test_soilscout_style_field_names(self):
        """Alternative 'access' / 'refresh' field names (e.g. SoilScout) are accepted."""
        payload = {
            'access': 'acc_soilscout',
            'refresh': 'ref_soilscout',
        }
        with patch('apps.integrations.auth_handlers.requests.post',
                   return_value=mock_token_response(payload)):
            result = _do_token_request('https://soilscouts.fi/api/v1/auth/login/', {}, 1000.0)

        assert result['access_token'] == 'acc_soilscout'
        assert result['refresh_token'] == 'ref_soilscout'
        # No expires_in returned — should default to 3600
        assert result['expires_at'] == 4600.0

    def test_missing_access_token_raises(self):
        """Response with no recognised access token field raises AuthError."""
        with patch('apps.integrations.auth_handlers.requests.post',
                   return_value=mock_token_response({'token': 'weird'})):
            with pytest.raises(AuthError, match='missing access_token'):
                _do_token_request('https://example.com/token', {}, 1000.0)

    def test_http_error_raises_auth_error(self):
        import requests as req_lib
        with patch('apps.integrations.auth_handlers.requests.post',
                   side_effect=req_lib.RequestException('connection refused')):
            with pytest.raises(AuthError, match='Token request failed'):
                _do_token_request('https://example.com/token', {}, 1000.0)


# ---------------------------------------------------------------------------
# _refresh_token — separate refresh_url support
# ---------------------------------------------------------------------------

class TestRefreshToken:

    def test_uses_refresh_url_when_present(self):
        """provider.refresh_url is used instead of token_url when set."""
        provider = make_provider('oauth2_password')
        provider.token_url = 'https://example.com/token'
        provider.refresh_url = 'https://soilscouts.fi/api/v1/auth/token/refresh/'
        payload = {'access': 'new_acc', 'refresh': 'new_ref'}
        captured_url = []

        def fake_post(url, **kwargs):
            captured_url.append(url)
            return mock_token_response(payload)

        with patch('apps.integrations.auth_handlers.requests.post', side_effect=fake_post):
            result = _refresh_token(provider, {}, 'old_refresh_token', 1000.0)

        assert captured_url[0] == 'https://soilscouts.fi/api/v1/auth/token/refresh/'
        assert result['access_token'] == 'new_acc'

    def test_falls_back_to_token_url_when_no_refresh_url(self):
        """token_url is used for refresh when refresh_url is blank."""
        provider = make_provider('oauth2_password')
        provider.token_url = 'https://example.com/token'
        provider.refresh_url = ''
        payload = {'access_token': 'new_acc', 'refresh_token': 'new_ref'}
        captured_url = []

        def fake_post(url, **kwargs):
            captured_url.append(url)
            return mock_token_response(payload)

        with patch('apps.integrations.auth_handlers.requests.post', side_effect=fake_post):
            _refresh_token(provider, {}, 'old_refresh_token', 1000.0)

        assert captured_url[0] == 'https://example.com/token'

    def test_no_client_credentials_omits_grant_type(self):
        """Providers without client_id/secret (e.g. SoilScout) get a minimal payload."""
        provider = make_provider('oauth2_password')
        provider.token_url = 'https://soilscouts.fi/api/v1/auth/login/'
        provider.refresh_url = 'https://soilscouts.fi/api/v1/auth/token/refresh/'
        payload = {'access': 'acc', 'refresh': 'ref'}
        captured_data = []

        def fake_post(url, data=None, **kwargs):
            captured_data.append(data)
            return mock_token_response(payload)

        with patch('apps.integrations.auth_handlers.requests.post', side_effect=fake_post):
            _refresh_token(provider, {}, 'my_refresh_token', 1000.0)

        sent = captured_data[0]
        assert 'grant_type' not in sent
        assert sent['refresh_token'] == 'my_refresh_token'

    def test_with_client_credentials_includes_grant_type(self):
        """Standard OAuth2 providers with client_id get grant_type in refresh payload."""
        provider = make_provider('oauth2_client_credentials')
        provider.token_url = 'https://example.com/token'
        provider.refresh_url = ''
        credentials = {'client_id': 'cid', 'client_secret': 'csecret'}
        payload = {'access_token': 'acc', 'refresh_token': 'ref'}
        captured_data = []

        def fake_post(url, data=None, **kwargs):
            captured_data.append(data)
            return mock_token_response(payload)

        with patch('apps.integrations.auth_handlers.requests.post', side_effect=fake_post):
            _refresh_token(provider, credentials, 'my_refresh_token', 1000.0)

        sent = captured_data[0]
        assert sent['grant_type'] == 'refresh_token'
        assert sent['client_id'] == 'cid'


# ---------------------------------------------------------------------------
# OAuth2 full flow — cached token reuse
# ---------------------------------------------------------------------------

class TestOAuth2Flow:

    def test_uses_cached_token_when_valid(self):
        """Valid cached token is returned without any HTTP calls."""
        import time
        provider = make_provider('oauth2_password')
        cache = {
            'access_token': 'cached_token',
            'expires_at': time.time() + 3600,
        }
        with patch('apps.integrations.auth_handlers.requests.post') as mock_post:
            headers, params, updated = get_auth_session(provider, {}, cache)
            mock_post.assert_not_called()

        assert headers == {'Authorization': 'Bearer cached_token'}
        assert updated is None

    def test_soilscout_full_login_flow(self):
        """End-to-end: oauth2_password with SoilScout-style response fields.

        token_url and refresh_url are on the provider; credentials only
        contain the tenant's username and password.
        """
        provider = make_provider('oauth2_password')
        provider.name = 'SoilScout'
        provider.token_url = 'https://soilscouts.fi/api/v1/auth/login/'
        provider.refresh_url = 'https://soilscouts.fi/api/v1/auth/token/refresh/'
        credentials = {'username': 'scout_user', 'password': 'scout_pass'}
        payload = {'access': 'fresh_access', 'refresh': 'fresh_refresh'}

        with patch('apps.integrations.auth_handlers.requests.post',
                   return_value=mock_token_response(payload)):
            headers, params, updated = get_auth_session(provider, credentials, {})

        assert headers == {'Authorization': 'Bearer fresh_access'}
        assert updated['access_token'] == 'fresh_access'
        assert updated['refresh_token'] == 'fresh_refresh'

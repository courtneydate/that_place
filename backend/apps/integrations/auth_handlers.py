"""Authentication handlers for 3rd party API providers.

Builds request headers/params for each auth type defined in
ThirdPartyAPIProvider.AuthType. For OAuth2 types, handles token fetching
and refresh, storing state in DataSource.auth_token_cache.

Ref: SPEC.md § Feature: Data Ingestion — 3rd Party APIs
"""
import base64
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Refresh token this many seconds before it actually expires to avoid races
TOKEN_REFRESH_BUFFER_SECONDS = 60

# HTTP timeout for token requests (seconds)
TOKEN_REQUEST_TIMEOUT = 10


class AuthError(Exception):
    """Raised when authentication fails or a token cannot be obtained/refreshed."""


def get_auth_session(
    provider,
    credentials: dict,
    token_cache: dict,
) -> tuple[dict, dict, Optional[dict]]:
    """Return (headers, params, updated_token_cache) for a provider request.

    For stateless auth types (api_key_header, bearer_token, basic_auth,
    api_key_query) the updated_token_cache is always None.
    For oauth2 types, updated_token_cache is non-None only when a new token
    was fetched (caller should persist it to DataSource.auth_token_cache).

    Raises AuthError if authentication cannot be established.
    """
    auth_type = provider.auth_type

    if auth_type == 'api_key_header':
        return _api_key_header(credentials), {}, None
    elif auth_type == 'api_key_query':
        return {}, _api_key_query(credentials), None
    elif auth_type == 'bearer_token':
        return _bearer_token(credentials), {}, None
    elif auth_type == 'basic_auth':
        return _basic_auth(credentials), {}, None
    elif auth_type in ('oauth2_client_credentials', 'oauth2_password'):
        headers, updated_cache = _oauth2(
            auth_type, provider, credentials, token_cache or {},
        )
        return headers, {}, updated_cache
    else:
        raise AuthError(f'Unknown auth_type: {auth_type!r}')


# ---------------------------------------------------------------------------
# Stateless auth builders
# ---------------------------------------------------------------------------

def _api_key_header(credentials: dict) -> dict:
    """Build headers for api_key_header auth.

    credentials keys are header names; values are header values.
    e.g. {'X-API-Key': 'abc123'}
    """
    return dict(credentials)


def _api_key_query(credentials: dict) -> dict:
    """Build query params for api_key_query auth.

    credentials keys are query param names; values are param values.
    e.g. {'api_key': 'abc123'}
    """
    return dict(credentials)


def _bearer_token(credentials: dict) -> dict:
    """Build headers for bearer_token auth.

    Expects credentials: {token: str}
    """
    return {'Authorization': f'Bearer {credentials["token"]}'}


def _basic_auth(credentials: dict) -> dict:
    """Build Authorization header for basic_auth.

    Expects credentials: {username: str, password: str}
    """
    raw = f'{credentials["username"]}:{credentials["password"]}'.encode()
    encoded = base64.b64encode(raw).decode()
    return {'Authorization': f'Basic {encoded}'}


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------

def _oauth2(
    auth_type: str,
    provider,
    credentials: dict,
    token_cache: dict,
) -> tuple[dict, Optional[dict]]:
    """Fetch or reuse an OAuth2 token and return (headers, updated_cache).

    Token and refresh URLs are read from the provider record, not from
    tenant credentials. Returns updated_cache=None when the cached token
    is still valid.
    """
    now = datetime.now(tz=timezone.utc).timestamp()

    # Use cached token if still valid
    if token_cache.get('access_token'):
        expires_at = token_cache.get('expires_at', 0)
        if expires_at - TOKEN_REFRESH_BUFFER_SECONDS > now:
            return {'Authorization': f'Bearer {token_cache["access_token"]}'}, None

    # Try refresh_token first (avoids re-sending user credentials)
    if token_cache.get('refresh_token'):
        try:
            new_cache = _refresh_token(provider, credentials, token_cache['refresh_token'], now)
            logger.debug('OAuth2 token refreshed via refresh_token')
            return {'Authorization': f'Bearer {new_cache["access_token"]}'}, new_cache
        except AuthError:
            logger.warning('refresh_token attempt failed; re-authenticating from credentials')

    # Full authentication from credentials
    new_cache = _fetch_token(auth_type, provider, credentials, now)
    logger.debug('OAuth2 token fetched via %s grant', auth_type)
    return {'Authorization': f'Bearer {new_cache["access_token"]}'}, new_cache


def _fetch_token(auth_type: str, provider, credentials: dict, now: float) -> dict:
    """Fetch a fresh OAuth2 token using the appropriate grant type.

    token_url is taken from the provider record.
    """
    token_url = provider.token_url
    if not token_url:
        raise AuthError(f'Provider "{provider.name}" has no token_url configured.')

    if auth_type == 'oauth2_client_credentials':
        data = {
            'grant_type': 'client_credentials',
            'client_id': credentials['client_id'],
            'client_secret': credentials['client_secret'],
        }
    else:  # oauth2_password
        data = {
            'username': credentials['username'],
            'password': credentials['password'],
        }
        # Only include OAuth2 grant fields when the provider uses client
        # credentials (e.g. standard OAuth2 servers).  Providers like
        # SoilScout only accept {username, password} and reject extra fields.
        client_id = credentials.get('client_id', '')
        client_secret = credentials.get('client_secret', '')
        if client_id or client_secret:
            data['grant_type'] = 'password'
            data['client_id'] = client_id
            data['client_secret'] = client_secret

    return _do_token_request(token_url, data, now)


def _refresh_token(provider, credentials: dict, refresh_token: str, now: float) -> dict:
    """Refresh an OAuth2 token using an existing refresh_token.

    Uses provider.refresh_url when set (e.g. SoilScout uses a separate
    /auth/token/refresh/ endpoint); falls back to provider.token_url.
    Omits grant_type/client_id when no client credentials are configured,
    to support providers that don't accept standard OAuth2 form fields.
    """
    refresh_url = provider.refresh_url or provider.token_url
    if not refresh_url:
        raise AuthError(f'Provider "{provider.name}" has no token_url configured.')
    data = {'refresh_token': refresh_token}
    client_id = credentials.get('client_id', '')
    client_secret = credentials.get('client_secret', '')
    if client_id or client_secret:
        data['grant_type'] = 'refresh_token'
        data['client_id'] = client_id
        data['client_secret'] = client_secret
    return _do_token_request(refresh_url, data, now)


def _do_token_request(token_url: str, data: dict, now: float) -> dict:
    """POST to a token endpoint and return a normalised cache dict.

    Accepts both standard OAuth2 field names (access_token, refresh_token)
    and alternative names used by some providers (access, refresh) so that
    non-standard JWT login endpoints (e.g. SoilScout /auth/login/) work
    without a custom handler.
    """
    try:
        resp = requests.post(token_url, data=data, timeout=TOKEN_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise AuthError(f'Token request failed: {exc}') from exc

    token_data = resp.json()

    # Normalise access token field — accept 'access_token' or 'access'
    access_token = token_data.get('access_token') or token_data.get('access')
    if not access_token:
        raise AuthError('Token response missing access_token')

    # Normalise refresh token field — accept 'refresh_token' or 'refresh'
    refresh_token = token_data.get('refresh_token') or token_data.get('refresh')

    expires_in = token_data.get('expires_in', 3600)
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': now + expires_in,
    }

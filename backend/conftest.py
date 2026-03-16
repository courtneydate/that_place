"""Root pytest configuration and shared fixtures for Fieldmouse tests."""
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    """Unauthenticated DRF API client."""
    return APIClient()

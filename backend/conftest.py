"""Root pytest configuration and shared fixtures for That Place tests."""
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    """Unauthenticated DRF API client."""
    return APIClient()

"""Sprint 23b tests — Reference Dataset delete guard (feeds).

A Reference Dataset in use by any TenantDatasetAssignment cannot be deleted;
the endpoint returns 409 with the affected tenant/site assignments. An unused
dataset is still deletable.

Ref: SPEC.md §9; ROADMAP Sprint 23b
"""
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Tenant, User
from apps.feeds.models import ReferenceDataset, TenantDatasetAssignment


def make_platform_admin(email='pa-feeds@example.com'):
    """Create a That Place platform admin (no tenant)."""
    return User.objects.create_user(
        email=email, password='testpass123', is_that_place_admin=True,
    )


def make_dataset(slug='s23b-dataset'):
    """Create a minimal Reference Dataset."""
    return ReferenceDataset.objects.create(
        name='S23b Dataset',
        slug=slug,
        scope='system',
        dimension_schema={},
        value_schema={},
    )


def auth(user):
    """Return an APIClient authenticated as the given user."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestReferenceDatasetDeleteGuard:
    """Deletion is blocked while a dataset is referenced by any assignment."""

    def test_unused_dataset_can_be_deleted(self):
        """A dataset with no assignments is deleted normally (204)."""
        dataset = make_dataset()
        resp = auth(make_platform_admin()).delete(
            f'/api/v1/reference-datasets/{dataset.pk}/',
        )
        assert resp.status_code == 204
        assert not ReferenceDataset.objects.filter(pk=dataset.pk).exists()

    def test_in_use_dataset_delete_blocked_with_409(self):
        """A dataset referenced by an assignment is blocked with a 409."""
        dataset = make_dataset()
        tenant = Tenant.objects.create(name='DSGuardT', slug='dsguardt')
        TenantDatasetAssignment.objects.create(
            tenant=tenant,
            dataset=dataset,
            dimension_filter={},
            effective_from=date(2025, 1, 1),
        )
        resp = auth(make_platform_admin()).delete(
            f'/api/v1/reference-datasets/{dataset.pk}/',
        )
        assert resp.status_code == 409
        assert resp.data['error']['code'] == 'dataset_in_use'
        assignments = resp.data['error']['details']['assignments']
        assert assignments[0]['tenant'] == 'DSGuardT'
        # The dataset must survive the blocked delete.
        assert ReferenceDataset.objects.filter(pk=dataset.pk).exists()

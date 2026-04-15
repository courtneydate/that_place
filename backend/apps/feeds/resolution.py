"""ReferenceDataset row resolution logic.

resolve_dataset_assignment(assignment) — given a TenantDatasetAssignment,
    returns the currently applicable row's values dict, or raises
    ResolutionError if no row matches or multiple rows match.

resolve_reference_value(assignment, value_key, dimension_overrides) — returns
    a single scalar value from the resolved row for use in rule evaluation.

Resolution order (per SPEC.md § Key Business Rules):
  1. Filter rows by dimension_filter (merged with any dimension_overrides)
  2. Filter by version (pinned or latest active)
  3. If has_time_of_use, filter by current day/time in tenant timezone
  4. Return matching row's values
  5. If multiple rows match → ResolutionError (misconfiguration guard)

Ref: SPEC.md § Feature: Reference Datasets, § Key Business Rules
"""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class ResolutionError(Exception):
    """Raised when a dataset row cannot be unambiguously resolved."""


def resolve_dataset_assignment(assignment, dimension_overrides: dict | None = None) -> dict:
    """Resolve the currently applicable row for a TenantDatasetAssignment.

    Returns the matching row's values dict.
    Raises ResolutionError if no row matches or multiple rows match (misconfiguration).

    Args:
        assignment:          TenantDatasetAssignment instance.
        dimension_overrides: Optional JSONB — merged over assignment.dimension_filter.
                             Used by reference_value rule conditions to narrow lookup.
    """
    from .models import ReferenceDatasetRow

    dataset = assignment.dataset
    today = date.today()

    # --- Build effective dimension filter ---
    effective_filter = dict(assignment.dimension_filter or {})
    if dimension_overrides:
        effective_filter.update(dimension_overrides)

    # --- Base queryset: active rows for this dataset ---
    qs = ReferenceDatasetRow.objects.filter(dataset=dataset, is_active=True)

    # --- Version filter ---
    if assignment.version:
        qs = qs.filter(version=assignment.version)
    elif dataset.has_version:
        # Use latest active version (lexicographic — works for "YYYY-YY" format)
        latest_version = (
            qs.exclude(version__isnull=True)
            .exclude(version='')
            .order_by('-version')
            .values_list('version', flat=True)
            .first()
        )
        if not latest_version:
            raise ResolutionError(
                f'Dataset "{dataset.slug}" has no active versioned rows.'
            )
        qs = qs.filter(version=latest_version)

    # --- Date validity filter ---
    qs = qs.filter(
        models_Q_valid_today(today)
    )

    # --- Dimension filter: each row's dimensions must contain all effective_filter keys ---
    # PostgreSQL JSONB containment (@>) is ideal; fall back to Python filter for portability.
    candidates = [
        row for row in qs
        if _dimensions_match(row.dimensions, effective_filter)
    ]

    if not candidates:
        raise ResolutionError(
            f'No active rows found for dataset "{dataset.slug}" '
            f'with filter {effective_filter}.'
        )

    # --- Time-of-use filter ---
    if dataset.has_time_of_use:
        tenant_tz = ZoneInfo(assignment.tenant.timezone or 'Australia/Sydney')
        now_local = datetime.now(tenant_tz)
        current_day = now_local.weekday()  # 0=Mon … 6=Sun
        current_time = now_local.time().replace(second=0, microsecond=0)

        tou_matches = [
            row for row in candidates
            if _tou_matches(row, current_day, current_time)
        ]

        if not tou_matches:
            raise ResolutionError(
                f'No rows for dataset "{dataset.slug}" match the current time '
                f'({now_local.strftime("%A %H:%M")} {tenant_tz.zone}).'
            )
        candidates = tou_matches

    if len(candidates) > 1:
        raise ResolutionError(
            f'Ambiguous resolution for dataset "{dataset.slug}": '
            f'{len(candidates)} rows match. Ensure rows have non-overlapping '
            f'dimension/TOU combinations.'
        )

    return candidates[0].values


def resolve_reference_value(
    assignment,
    value_key: str,
    dimension_overrides: dict | None = None,
) -> float | str | bool | None:
    """Resolve a single scalar value from a TenantDatasetAssignment.

    Used directly by the rule evaluation engine for reference_value conditions.

    Args:
        assignment:          TenantDatasetAssignment instance.
        value_key:           Which key to extract from the resolved row's values dict.
        dimension_overrides: Optional overrides merged over assignment.dimension_filter.

    Returns:
        The scalar value, or None if not present in the resolved row.

    Raises:
        ResolutionError if row resolution fails.
    """
    values = resolve_dataset_assignment(assignment, dimension_overrides=dimension_overrides)
    return values.get(value_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dimensions_match(row_dimensions: dict, filter_dict: dict) -> bool:
    """Return True if row_dimensions contains all key-value pairs in filter_dict."""
    if not filter_dict:
        return True
    for key, value in filter_dict.items():
        if str(row_dimensions.get(key, '')).lower() != str(value).lower():
            return False
    return True


def _tou_matches(row, current_day: int, current_time) -> bool:
    """Return True if the row's TOU config covers current_day and current_time.

    Handles overnight windows (e.g. time_from=21:00, time_to=07:00) by checking
    whether the window wraps midnight.
    """
    # No TOU config on this row → applies at all times
    if row.applicable_days is None and row.time_from is None and row.time_to is None:
        return True

    # Day check
    if row.applicable_days is not None and current_day not in row.applicable_days:
        return False

    # Time check
    if row.time_from is not None and row.time_to is not None:
        t_from = row.time_from
        t_to = row.time_to
        if t_from <= t_to:
            # Normal window (e.g. 07:00–21:00)
            if not (t_from <= current_time < t_to):
                return False
        else:
            # Overnight window (e.g. 21:00–07:00)
            if not (current_time >= t_from or current_time < t_to):
                return False

    return True


def models_Q_valid_today(today: date):
    """Return a Q object filtering rows that are valid today.

    A row is valid when:
      - valid_from is null OR valid_from <= today
      - valid_to is null OR valid_to >= today
    """
    from django.db.models import Q
    return (
        Q(valid_from__isnull=True) | Q(valid_from__lte=today)
    ) & (
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    )

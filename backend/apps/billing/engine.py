"""Billing engine — Sprint 31 + Sprint 33.

Five-step pipeline executed by ``apps.billing.tasks.run_billing_run``:

  1. resolve_scope     — validate site, find active BillingAccounts in the
                         period, clamp each account's billable window by
                         activated_at / deactivated_at.
  2. snapshot          — walk each (account, billed stream), fetch the run's
                         IntervalAggregates over the (possibly clamped)
                         window, write BillingRunSnapshot rows.
  3. allocate_solar    — Sprint 33. Hierarchical sites only (no-op otherwise):
                         per interval compute the solar pool
                         (Σ generation − gate_export) and allocate it across
                         active child accounts pro-rata by grid_import; write
                         SolarAllocationRecord rows.
  4. compute_line_items — split each interval at TOU boundaries via
                         tariff_resolver, accumulate per (account, stream,
                         period_name) totals, write BillingLineItem rows:
                         `energy`, `supply`, and `credit` (feed-in). For
                         hierarchical embedded-network tenants the consumption
                         line splits into two energy legs — solar-allocated kWh
                         at the solar rate, remaining at the grid rate.
  5. mark_draft        — set status=draft, computed_at=now.

Each step is its own DB transaction. Any exception sets the run's
failed_step + failure_detail; the caller's task records the run as
``failed`` and the ``retry`` endpoint resumes from the failed step.

Per Sprint 31 design decisions:
  - site_id is required; billing_account_ids filters within the site
  - mid-cycle pro-rata: window clamped to
    [activated_at, deactivated_at] ∩ [period_start, period_end]
  - Stream-specific tariff assignment wins over catch-all
  - TOU boundaries are split (line items aggregated per (account, stream,
    period_name) across the run)
  - `credit` line kind emitted when the resolved tariff is on a
    billing_role=grid_export stream
  - GST per line: amount_cents * tenant.gst_rate, half-up rounding

Per Sprint 33 design decisions:
  - solar pool = max(0, Σ generation − gate_export), clamped to total child
    import (a child can't be allocated more solar than it consumed);
    bess_discharge is excluded (it carries its own billing_role)
  - pro-rata allocation by grid_import; largest-remainder rounding so the
    children's allocations sum to the pool exactly at 6 dp
  - the embedded-network tenant consumption line splits into two energy legs
    resolved via BillingAccountTariffAssignment.applies_to_role
    (consumption_from_solar = solar leg, consumption = grid leg)

Ref: SPEC.md § Feature: Billing Runs & Invoicing
     SPEC.md § Feature: Embedded-Network Billing (Hierarchical Metering)
     ROADMAP Sprint 31, Sprint 33
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public step API
# ---------------------------------------------------------------------------

class StepError(RuntimeError):
    """Raised when a billing engine step fails. ``step`` records which one."""

    def __init__(self, step, message: str):
        super().__init__(f'{step}: {message}')
        self.step = step
        self.message = message


# ---------------------------------------------------------------------------
# Step 1 — resolve_scope
# ---------------------------------------------------------------------------

def step_resolve_scope(billing_run) -> None:
    """Validate the run scope and gather active billing accounts.

    Stored on the run via a side-effect: ``billing_run._resolved_scope`` (an
    in-memory cache) holds the list of (account, account_window_start,
    account_window_end) tuples for downstream steps. The DB itself stores
    nothing yet — we only persist after snapshot.
    """
    from .models import BillingAccount, BillingRun

    if not billing_run.site_id:
        raise StepError(BillingRun.Step.RESOLVE_SCOPE, 'BillingRun.site is required.')
    if billing_run.period_end <= billing_run.period_start:
        raise StepError(
            BillingRun.Step.RESOLVE_SCOPE,
            'period_end must be strictly after period_start.',
        )

    # Candidate accounts: same tenant, active, within explicit filter (if any).
    qs = BillingAccount.objects.filter(
        tenant_id=billing_run.tenant_id,
        is_active=True,
    )
    if billing_run.billing_account_ids:
        qs = qs.filter(pk__in=billing_run.billing_account_ids)

    accounts_in_scope = []
    for account in qs:
        window_start, window_end = _clamp_account_window(
            account, billing_run.period_start, billing_run.period_end,
        )
        if window_end <= window_start:
            # Account was deactivated before the run period (or activates after)
            continue
        accounts_in_scope.append((account, window_start, window_end))

    if not accounts_in_scope:
        raise StepError(
            BillingRun.Step.RESOLVE_SCOPE,
            'No active billing accounts in the run scope.',
        )

    billing_run._resolved_scope = accounts_in_scope


def _clamp_account_window(account, period_start: datetime, period_end: datetime):
    """Clamp the run window to the account's lifecycle.

    Returns (window_start, window_end). Both inputs and outputs are aware UTC
    datetimes.
    """
    start = period_start
    if account.activated_at:
        start = max(start, account.activated_at)
    end = period_end
    if account.deactivated_at:
        end = min(end, account.deactivated_at)
    return start, end


# ---------------------------------------------------------------------------
# Step 2 — snapshot
# ---------------------------------------------------------------------------

def step_snapshot(billing_run) -> None:
    """Walk each account's billed streams and snapshot the aggregates.

    Writes one BillingRunSnapshot per (account, stream). Idempotent via
    update_or_create on the unique constraint — running step_snapshot a
    second time produces the same rows.

    A stream linked to multiple active accounts in the same run window is a
    misconfiguration: raise.
    """
    from apps.readings.models import IntervalAggregate

    from .models import (
        BillingAccountMeter,
        BillingRun,
        BillingRunSnapshot,
    )

    accounts_in_scope = getattr(billing_run, '_resolved_scope', None)
    if accounts_in_scope is None:
        raise StepError(
            BillingRun.Step.SNAPSHOT,
            'resolve_scope must run before snapshot.',
        )

    # Build the (stream → [(account, window)]) map and detect double-bookings.
    stream_to_accounts: dict[int, list[tuple]] = defaultdict(list)
    for account, win_start, win_end in accounts_in_scope:
        meters = BillingAccountMeter.objects.filter(
            billing_account=account,
            effective_from__lte=win_end.date(),
        ).filter(
            _q_or_null('effective_to__gte', win_start.date()),
        ).select_related('stream')
        for meter_link in meters:
            stream_to_accounts[meter_link.stream_id].append(
                (account, win_start, win_end, meter_link.stream),
            )

    for stream_id, claims in stream_to_accounts.items():
        if len(claims) > 1:
            raise StepError(
                BillingRun.Step.SNAPSHOT,
                f'Stream {stream_id} is linked to multiple active billing '
                f'accounts in the run window '
                f'(accounts={[c[0].id for c in claims]}). Fix the meter links.',
            )

    period = billing_run.aggregate_period
    with transaction.atomic():
        # Wipe any prior snapshot for this run (handles retry/recompute).
        BillingRunSnapshot.objects.filter(billing_run=billing_run).delete()

        for stream_id, claims in stream_to_accounts.items():
            account, win_start, win_end, stream = claims[0]
            aggs = list(
                IntervalAggregate.objects.filter(
                    stream_id=stream_id,
                    period=period,
                    aggregation_kind='sum',  # energy streams aggregate as sum
                    period_start__gte=win_start,
                    period_start__lt=win_end,
                )
            )
            total = Decimal('0')
            quality_summary: dict[str, int] = defaultdict(int)
            agg_ids = []
            for agg in aggs:
                agg_ids.append(agg.id)
                if agg.value is not None:
                    total += Decimal(str(agg.value))
                for q, n in (agg.quality_breakdown or {}).items():
                    quality_summary[q] += n
                if agg.count == 0:
                    quality_summary.setdefault('gap', 0)
                    quality_summary['gap'] += 1

            BillingRunSnapshot.objects.create(
                billing_run=billing_run,
                billing_account=account,
                stream=stream,
                interval_aggregate_ids=agg_ids,
                computed_kwh=total,
                quality_summary=dict(quality_summary),
            )


def _q_or_null(field_lookup: str, value):
    from django.db.models import Q

    field_name = field_lookup.split('__', 1)[0]
    return Q(**{field_lookup: value}) | Q(**{f'{field_name}__isnull': True})


# ---------------------------------------------------------------------------
# Step 3 — allocate_solar (Sprint 33, hierarchical sites only)
# ---------------------------------------------------------------------------

def step_allocate_solar(billing_run) -> None:
    """Compute per-interval solar allocation for a hierarchical billing run.

    No-op (and clears any stale records) when the site is not hierarchical —
    PPA / single-tier runs skip straight through.

    For a hierarchical site, per interval:
      pool = max(0, Σ generation − gate_export)        # solar kept on-site
      pool = min(pool, Σ child grid_import)            # can't exceed consumption
    then allocate ``pool`` across active child accounts pro-rata by each
    child's grid_import (largest-remainder rounding → children sum to pool
    exactly at 6 dp). One SolarAllocationRecord per (interval, child).

    Idempotent: wipes and rewrites this run's records on every execution, so
    recompute / retry-from-here produce the identical end state.
    """
    from apps.readings.models import Stream

    from .models import (
        BillingAccount,
        BillingAccountMeter,
        BillingRun,
        SolarAllocationRecord,
    )

    site = billing_run.site

    with transaction.atomic():
        SolarAllocationRecord.objects.filter(billing_run=billing_run).delete()

        if not site.is_hierarchical:
            return

        accounts_in_scope = getattr(billing_run, '_resolved_scope', None)
        if accounts_in_scope is None:
            step_resolve_scope(billing_run)
            accounts_in_scope = billing_run._resolved_scope

        period = billing_run.aggregate_period
        win_start, win_end = billing_run.period_start, billing_run.period_end

        # Site-level solar pool inputs. generation excludes bess_discharge by
        # construction (battery output carries billing_role=bess_discharge,
        # never generation). gate_export is the site's grid_export (≤ 1 gate
        # meter per site in v1, so this is the gate's export).
        gen_ids = _stream_ids_by_role(site, Stream.BillingRole.GENERATION)
        export_ids = _stream_ids_by_role(site, Stream.BillingRole.GRID_EXPORT)
        gen_by_ts = _sum_aggregates_by_ts(gen_ids, period, win_start, win_end)
        export_by_ts = _sum_aggregates_by_ts(export_ids, period, win_start, win_end)

        # Active embedded-network tenant (child) accounts with a grid_import
        # stream, each clamped to its own billable window.
        children = []  # (account_id, child_win_start, child_win_end, import_by_ts)
        for account, child_start, child_end in accounts_in_scope:
            if account.account_type != BillingAccount.AccountType.EN_TENANT:
                continue
            import_ids = _child_import_stream_ids(
                BillingAccountMeter, account, child_start, child_end,
            )
            if not import_ids:
                continue
            import_by_ts = _sum_aggregates_by_ts(
                import_ids, period, child_start, child_end,
            )
            children.append((account.id, child_start, child_end, import_by_ts))

        if not children:
            return

        timestamps = sorted(set(gen_by_ts) | set(export_by_ts))
        records = []
        for ts in timestamps:
            pool = gen_by_ts.get(ts, Decimal('0')) - export_by_ts.get(ts, Decimal('0'))
            if pool <= 0:
                continue  # gate_export ≥ generation → nothing stayed on-site

            imports = {}
            for account_id, child_start, child_end, import_by_ts in children:
                if not (child_start <= ts < child_end):
                    continue
                imp = import_by_ts.get(ts, Decimal('0'))
                if imp > 0:
                    imports[account_id] = imp

            total_import = sum(imports.values(), Decimal('0'))
            if total_import <= 0:
                continue

            # A child can't be allocated more solar than it actually consumed,
            # so the allocatable pool is capped at total child import. With
            # physically valid data (pool ≤ total consumption) this is a no-op.
            effective_pool = min(pool, total_import)
            allocations = _allocate_pool(effective_pool, imports)
            for account_id, allocated in allocations.items():
                records.append(SolarAllocationRecord(
                    billing_run=billing_run,
                    billing_account_id=account_id,
                    interval_start=ts,
                    allocated_kwh=allocated,
                    pool_kwh=effective_pool,
                    child_grid_import_kwh=imports[account_id],
                    allocation_method=(
                        SolarAllocationRecord.AllocationMethod.PRO_RATA_CONSUMPTION
                    ),
                ))

        if records:
            SolarAllocationRecord.objects.bulk_create(records)

    _ = BillingRun  # imported for symmetry with sibling steps


def _stream_ids_by_role(site, role) -> list[int]:
    """Return ids of streams at ``site`` carrying ``billing_role == role``."""
    from apps.readings.models import Stream

    return list(
        Stream.objects
        .filter(device__site=site, billing_role=role)
        .values_list('id', flat=True)
    )


def _child_import_stream_ids(meter_model, account, win_start, win_end) -> list[int]:
    """Return grid_import stream ids linked to ``account`` over its window."""
    from apps.readings.models import Stream

    links = (
        meter_model.objects
        .filter(billing_account=account, effective_from__lte=win_end.date())
        .filter(_q_or_null('effective_to__gte', win_start.date()))
        .select_related('stream')
    )
    return [
        link.stream_id
        for link in links
        if link.stream.billing_role == Stream.BillingRole.GRID_IMPORT
    ]


def _sum_aggregates_by_ts(stream_ids, period, win_start, win_end) -> dict:
    """Sum sum-kind IntervalAggregates across ``stream_ids`` keyed by period_start."""
    from collections import defaultdict

    from apps.readings.models import IntervalAggregate

    out: dict = defaultdict(lambda: Decimal('0'))
    if not stream_ids:
        return out
    aggs = IntervalAggregate.objects.filter(
        stream_id__in=stream_ids,
        period=period,
        aggregation_kind='sum',
        period_start__gte=win_start,
        period_start__lt=win_end,
    )
    for agg in aggs:
        if agg.value is not None:
            out[agg.period_start] += Decimal(str(agg.value))
    return out


def _allocate_pool(pool: Decimal, imports: dict) -> dict:
    """Allocate ``pool`` across ``imports`` pro-rata, summing to ``pool`` exactly.

    Largest-remainder method at 6 dp: floor each raw share, then hand the
    leftover micro-kWh units to the accounts with the largest fractional
    remainders. Guarantees Σ allocations == pool with no rounding leakage.
    """
    q = Decimal('0.000001')
    total = sum(imports.values(), Decimal('0'))
    raw = {k: (pool * v / total) for k, v in imports.items()}
    floored = {k: r.quantize(q, rounding=ROUND_DOWN) for k, r in raw.items()}
    remainder = pool - sum(floored.values(), Decimal('0'))
    units = int((remainder / q).to_integral_value(rounding=ROUND_HALF_UP))

    # Order by descending fractional remainder; ties broken by account id for
    # determinism (reproducible runs).
    order = sorted(
        imports.keys(),
        key=lambda k: (raw[k] - floored[k], -k),
        reverse=True,
    )
    out = dict(floored)
    for i in range(units):
        out[order[i % len(order)]] += q
    return out


# ---------------------------------------------------------------------------
# Step 4 — compute_line_items
# ---------------------------------------------------------------------------

def step_compute_line_items(billing_run) -> None:
    """Resolve tariffs per interval, split at TOU boundaries, emit line items.

    For each snapshot row:
      - Walk every IntervalAggregate the snapshot referenced
      - Find the active tariff assignment (stream-specific or catch-all)
      - Split the interval at TOU boundaries via tariff_resolver.split_interval
      - Multiply each segment's kWh share by its rate
      - Accumulate per (account, stream, period_name)
      - Emit one BillingLineItem per (account, stream, period_name) group
      - Emit one `supply` line per account per day in the billable window
      - `credit` instead of `energy` when stream.billing_role == 'grid_export'
    """
    from apps.readings.models import IntervalAggregate, Stream

    from .models import (
        BillingAccount,
        BillingLineItem,
        BillingRun,
        BillingRunSnapshot,
        SolarAllocationRecord,
    )
    from .tariff_resolver import (
        TariffResolutionError,
        derive_period_name,
        find_assignment,
        get_rate,
        split_interval,
    )

    tenant_tz = billing_run.timezone_snapshot
    gst_rate = Decimal(str(billing_run.tenant.gst_rate))

    accounts_in_scope = getattr(billing_run, '_resolved_scope', None)
    if accounts_in_scope is None:
        # Allow stand-alone re-runs of compute_line_items (retry from this step).
        step_resolve_scope(billing_run)
        accounts_in_scope = billing_run._resolved_scope

    account_windows = {a.id: (s, e) for (a, s, e) in accounts_in_scope}

    # Sprint 33: on a hierarchical site, embedded-network tenant consumption
    # splits into a solar leg + a grid leg. Load the per-(account, interval)
    # solar allocations written by step_allocate_solar.
    is_hierarchical = billing_run.site.is_hierarchical
    alloc_map: dict[int, dict] = defaultdict(dict)
    if is_hierarchical:
        for rec in SolarAllocationRecord.objects.filter(billing_run=billing_run):
            alloc_map[rec.billing_account_id][rec.interval_start] = rec.allocated_kwh

    with transaction.atomic():
        BillingLineItem.objects.filter(billing_run=billing_run).delete()

        snapshots = (
            BillingRunSnapshot.objects
            .filter(billing_run=billing_run)
            .select_related('billing_account', 'stream')
        )

        # Per-account aggregation: (stream_id, period_name) → (kwh, rate, line_kind, qualities)
        per_account_lines: dict[int, dict] = defaultdict(dict)
        # Per-account supply totals: account_id → set of dates (each day counts once)
        per_account_supply_days: dict[int, set] = defaultdict(set)
        # Per-account supply rates: account_id → {date: Decimal} (rate sampled per day)
        per_account_supply_rates: dict[int, dict] = defaultdict(dict)

        for snap in snapshots:
            account = snap.billing_account
            stream = snap.stream
            win_start, win_end = account_windows[account.id]

            # The tariff assignment is resolved as-of mid-window (assignments
            # are date-bounded and rarely change inside a run period; mid-window
            # gives a stable choice).
            mid = win_start + (win_end - win_start) / 2

            # Sprint 33 — embedded-network tenant consumption splits into two
            # energy legs (solar-allocated + remaining grid). Handled separately
            # from the single-rate path below.
            is_split = (
                is_hierarchical
                and account.account_type == BillingAccount.AccountType.EN_TENANT
                and stream.billing_role == Stream.BillingRole.GRID_IMPORT
            )
            if is_split:
                try:
                    grid_assignment = _accumulate_split_legs(
                        billing_run, account, stream, snap, mid,
                        alloc_map.get(account.id, {}), tenant_tz,
                        per_account_lines[account.id],
                    )
                    supply_rate = _supply_rate_for_assignment(
                        grid_assignment, mid.date(), tenant_tz,
                    )
                except TariffResolutionError as exc:
                    raise StepError(
                        BillingRun.Step.COMPUTE_LINE_ITEMS, str(exc),
                    ) from exc
                if supply_rate is not None:
                    for day in _days_in_window(win_start, win_end, tenant_tz):
                        per_account_supply_days[account.id].add(day)
                        per_account_supply_rates[account.id][day] = supply_rate
                continue

            # Find the tariff assignment as-of mid-window.
            try:
                assignment = find_assignment(account, stream, mid.date())
            except TariffResolutionError as exc:
                raise StepError(
                    BillingRun.Step.COMPUTE_LINE_ITEMS, str(exc),
                ) from exc

            if assignment is None:
                # No tariff for this stream → skip (operator may be linking a
                # stream to an account purely for reporting). A grid_export
                # stream without a feed-in tariff produces no credit line.
                logger.info(
                    'Run %d: no tariff for account %d / stream %d — skipped',
                    billing_run.id, account.id, stream.id,
                )
                continue

            line_kind = (
                BillingLineItem.LineKind.CREDIT
                if stream.billing_role == Stream.BillingRole.GRID_EXPORT
                else BillingLineItem.LineKind.ENERGY
            )
            sign = Decimal('-1') if line_kind == BillingLineItem.LineKind.CREDIT else Decimal('1')

            # Walk this snapshot's intervals; sum into per (account, stream, period_name).
            aggs = list(
                IntervalAggregate.objects.filter(pk__in=snap.interval_aggregate_ids)
                .order_by('period_start')
            )
            for agg in aggs:
                if agg.value is None or agg.count == 0:
                    continue
                interval_kwh = Decimal(str(agg.value))
                interval_end = _interval_end(agg)
                for row, fraction in split_interval(
                    assignment, agg.period_start, interval_end, tenant_tz,
                ):
                    rate = get_rate(row)
                    if rate is None:
                        continue
                    period_name = derive_period_name(row)
                    seg_kwh = interval_kwh * fraction
                    key = (stream.id, period_name)
                    bucket = per_account_lines[account.id].setdefault(
                        key,
                        {
                            'stream': stream,
                            'line_kind': line_kind,
                            'period_name': period_name,
                            'rate': rate,
                            'kwh': Decimal('0'),
                            'sign': sign,
                            'quality': defaultdict(int),
                        },
                    )
                    bucket['kwh'] += seg_kwh
                    for q, n in (agg.quality_breakdown or {}).items():
                        bucket['quality'][q] += n

            # Pre-compute supply charge for each day in the account window.
            # The assignment's tariff template defines a daily fixed charge;
            # we sample the row once per day (TOU doesn't apply to supply).
            try:
                supply_rate = _supply_rate_for_assignment(assignment, mid.date(), tenant_tz)
            except TariffResolutionError as exc:
                raise StepError(BillingRun.Step.COMPUTE_LINE_ITEMS, str(exc)) from exc
            if supply_rate is not None:
                for day in _days_in_window(win_start, win_end, tenant_tz):
                    # Only count the supply day once per account, even when
                    # multiple streams are linked to it.
                    per_account_supply_days[account.id].add(day)
                    per_account_supply_rates[account.id][day] = supply_rate

        # Emit energy/credit line items.
        for account_id, buckets in per_account_lines.items():
            for (stream_id, period_name), data in buckets.items():
                kwh = data['kwh']
                rate = data['rate']
                amount = _round_cents(data['sign'] * kwh * rate)
                gst = _round_cents(Decimal(amount) * gst_rate)
                BillingLineItem.objects.create(
                    billing_run=billing_run,
                    billing_account_id=account_id,
                    stream=data['stream'],
                    line_kind=data['line_kind'],
                    period_name=period_name,
                    kwh=kwh.quantize(Decimal('0.000001')),
                    rate_cents_per_kwh=rate.quantize(Decimal('0.000001')),
                    amount_cents=amount,
                    gst_cents=gst,
                    quality_summary=dict(data['quality']),
                )

        # Emit supply line items — one per account.
        for account_id, days in per_account_supply_days.items():
            rates = per_account_supply_rates[account_id]
            # Sum each day's supply charge (rates can vary across versioned
            # tariff updates inside a single run, though it's rare).
            total = sum(
                (rates[d] for d in days),
                Decimal('0'),
            )
            amount = _round_cents(total)
            gst = _round_cents(Decimal(amount) * gst_rate)
            BillingLineItem.objects.create(
                billing_run=billing_run,
                billing_account_id=account_id,
                stream=None,
                line_kind=BillingLineItem.LineKind.SUPPLY,
                period_name='',
                kwh=None,
                rate_cents_per_kwh=None,
                amount_cents=amount,
                gst_cents=gst,
                quality_summary={},
            )

        # Sprint 34 — common-area apportionment (hierarchical sites only).
        _emit_common_area_shares(
            billing_run, accounts_in_scope, tenant_tz, gst_rate,
        )


def _accumulate_split_legs(
    billing_run, account, stream, snap, mid, child_alloc, tenant_tz, buckets,
):
    """Accumulate the two energy legs for an embedded-network tenant (Sprint 33).

    The child's measured grid_import splits each interval into:
      - a solar leg: the interval's SolarAllocationRecord kWh, priced at the
        ``consumption_from_solar`` tariff
      - a grid leg: the remaining consumption, priced at the ``consumption``
        tariff

    When no solar tariff is configured (or nothing was allocated this
    interval) the whole interval bills at the grid rate. Returns the resolved
    grid (consumption) assignment so the caller can derive the supply charge.
    """
    from apps.readings.models import IntervalAggregate, Stream

    from .models import BillingRun
    from .tariff_resolver import find_assignment

    solar_assignment = find_assignment(
        account, stream, mid.date(),
        applies_to_role=Stream.BillingRole.CONSUMPTION_FROM_SOLAR,
    )
    grid_assignment = find_assignment(
        account, stream, mid.date(),
        applies_to_role=Stream.BillingRole.CONSUMPTION,
    )
    if grid_assignment is None:
        raise StepError(
            BillingRun.Step.COMPUTE_LINE_ITEMS,
            f'Embedded-network tenant account "{account.name}" (id {account.id}) '
            f'has no grid tariff for its grid_import stream. Assign a tariff with '
            f'applies_to_role="consumption".',
        )

    aggs = list(
        IntervalAggregate.objects.filter(pk__in=snap.interval_aggregate_ids)
        .order_by('period_start')
    )
    for agg in aggs:
        if agg.value is None or agg.count == 0:
            continue
        import_kwh = Decimal(str(agg.value))
        allocated = child_alloc.get(agg.period_start, Decimal('0'))
        if allocated > import_kwh:
            allocated = import_kwh  # defensive: never allocate beyond consumption
        interval_end = _interval_end(agg)

        if solar_assignment is not None and allocated > 0:
            _accumulate_leg(
                buckets, solar_assignment, agg, allocated, interval_end,
                tenant_tz, stream, 'solar',
            )
            grid_kwh = import_kwh - allocated
        else:
            grid_kwh = import_kwh

        if grid_kwh > 0:
            _accumulate_leg(
                buckets, grid_assignment, agg, grid_kwh, interval_end,
                tenant_tz, stream, 'grid',
            )

    return grid_assignment


def _accumulate_leg(buckets, assignment, agg, leg_kwh, interval_end, tenant_tz, stream, leg):
    """TOU-split one energy leg and accumulate it into ``buckets``.

    The leg name is folded into period_name (e.g. "peak (solar)") so the solar
    and grid legs land in distinct buckets and read clearly on the invoice.
    """
    from .models import BillingLineItem
    from .tariff_resolver import derive_period_name, get_rate, split_interval

    for row, fraction in split_interval(
        assignment, agg.period_start, interval_end, tenant_tz,
    ):
        rate = get_rate(row)
        if rate is None:
            continue
        period_name = f'{derive_period_name(row)} ({leg})'
        key = (stream.id, period_name)
        bucket = buckets.setdefault(
            key,
            {
                'stream': stream,
                'line_kind': BillingLineItem.LineKind.ENERGY,
                'period_name': period_name,
                'rate': rate,
                'kwh': Decimal('0'),
                'sign': Decimal('1'),
                'quality': defaultdict(int),
            },
        )
        bucket['kwh'] += leg_kwh * fraction
        for q, n in (agg.quality_breakdown or {}).items():
            bucket['quality'][q] += n


def _interval_end(agg):
    """Return the exclusive end timestamp of an IntervalAggregate's bucket."""
    from apps.readings.aggregates import period_end

    return period_end(agg.period_start, agg.period)


def _days_in_window(window_start: datetime, window_end: datetime, tenant_tz: str):
    """Yield each tenant-local date that overlaps [window_start, window_end).

    A day is included if any part of it falls in the window. This matches the
    typical billing convention: a supply charge applies to any day the customer
    was connected, including partial days at the start/end of a tenancy.
    """
    tz = ZoneInfo(tenant_tz)
    start_local = window_start.astimezone(tz)
    end_local = window_end.astimezone(tz)
    cursor = start_local.date()
    end_date = (end_local - timedelta(microseconds=1)).date()
    while cursor <= end_date:
        yield cursor
        cursor = cursor + timedelta(days=1)


def _supply_rate_for_assignment(assignment, on_date: date, tenant_tz: str) -> Decimal | None:
    """Return the daily supply charge in cents for the assignment's tariff.

    Samples row resolution at noon local time on ``on_date`` to dodge any TOU
    overnight edge cases. Returns None when the tariff has no supply field.
    """
    from .tariff_resolver import (
        candidate_rows,
        get_supply_charge,
        row_at,
    )

    rows = candidate_rows(assignment, on_date)
    tz = ZoneInfo(tenant_tz)
    sample = datetime.combine(on_date, datetime.min.time(), tzinfo=tz).replace(hour=12)
    row = row_at(assignment, rows, sample)
    return get_supply_charge(row)


def _round_cents(decimal_value: Decimal) -> int:
    """Round a cent amount half-up to the nearest integer.

    Australian billing convention; Excel-compatible.
    """
    return int(Decimal(decimal_value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Sprint 34 — common-area apportionment (folded into compute_line_items)
# ---------------------------------------------------------------------------

def _common_area_meter_devices(site):
    """Devices on ``site`` whose MeterProfile role is common_area."""
    from apps.metering.models import MeterProfile

    return [
        mp.device for mp in
        MeterProfile.objects
        .filter(device__site=site, meter_role=MeterProfile.MeterRole.COMMON_AREA)
        .select_related('device')
    ]


def _meter_energy_stream_ids(device) -> list[int]:
    """Energy stream ids on a meter device (consumption / grid_import roles)."""
    from apps.readings.models import Stream

    return list(
        Stream.objects
        .filter(
            device=device,
            billing_role__in=[
                Stream.BillingRole.CONSUMPTION,
                Stream.BillingRole.GRID_IMPORT,
            ],
        )
        .values_list('id', flat=True)
    )


def _role_stream_ids(site, meter_role, billing_role) -> list[int]:
    """Stream ids on ``site`` devices with the given meter_role + billing_role."""
    from apps.metering.models import MeterProfile
    from apps.readings.models import Stream

    device_ids = (
        MeterProfile.objects
        .filter(device__site=site, meter_role=meter_role)
        .values_list('device_id', flat=True)
    )
    return list(
        Stream.objects
        .filter(device_id__in=list(device_ids), billing_role=billing_role)
        .values_list('id', flat=True)
    )


def _sum_aggregates_total(stream_ids, period, win_start, win_end) -> Decimal:
    """Total of sum-kind IntervalAggregate values across streams over a window."""
    from apps.readings.models import IntervalAggregate

    if not stream_ids:
        return Decimal('0')
    total = Decimal('0')
    for agg in IntervalAggregate.objects.filter(
        stream_id__in=stream_ids,
        period=period,
        aggregation_kind='sum',
        period_start__gte=win_start,
        period_start__lt=win_end,
    ):
        if agg.value is not None:
            total += Decimal(str(agg.value))
    return total


def _get_or_create_internal_account(tenant, device):
    """Idempotent `internal` billing account for a common-area meter device."""
    from .models import BillingAccount

    account, _ = BillingAccount.objects.get_or_create(
        tenant=tenant,
        customer_reference=f'common-area-meter-{device.id}',
        defaults={
            'name': f'Common Area — {device.name}',
            'account_type': BillingAccount.AccountType.INTERNAL,
        },
    )
    return account


def _apportionment_weights(method, children) -> dict:
    """Return {account_id: weight} for the site's apportionment method."""
    from apps.devices.models import Site
    from .models import BillingRun

    weights = {}
    for account, import_total, _stream in children:
        if method == Site.CommonAreaApportionmentMethod.EQUAL_SHARE:
            weights[account.id] = Decimal('1')
        elif method == Site.CommonAreaApportionmentMethod.BY_FLOOR_AREA:
            area = account.floor_area_sqm
            if area is None or Decimal(str(area)) <= 0:
                raise StepError(
                    BillingRun.Step.COMPUTE_LINE_ITEMS,
                    f'by_floor_area apportionment needs floor_area_sqm on every '
                    f'active child; account "{account.name}" (id {account.id}) is '
                    f'missing it.',
                )
            weights[account.id] = Decimal(str(area))
        else:  # PRO_RATA_CONSUMPTION (default)
            weights[account.id] = import_total if import_total > 0 else Decimal('0')
    return weights


def _representative_rate(account, import_stream, tenant_tz, mid_date):
    """The child's consumption (grid/EN) rate at mid-period, or None.

    Common-area apportioned energy is a period-level total, so it is costed at a
    single representative rate: the child's `consumption` tariff resolved at noon
    on the mid-period date. (TOU-splitting apportioned common-area energy is out
    of scope for v1.)
    """
    from apps.readings.models import Stream

    from .tariff_resolver import (
        candidate_rows,
        find_assignment,
        get_rate,
        row_at,
    )

    assignment = find_assignment(
        account, import_stream, mid_date,
        applies_to_role=Stream.BillingRole.CONSUMPTION,
    )
    if assignment is None:
        # Fall back to an untagged assignment (single-rate configs).
        assignment = find_assignment(account, import_stream, mid_date)
    if assignment is None:
        return None
    rows = candidate_rows(assignment, mid_date)
    tz = ZoneInfo(tenant_tz)
    sample = datetime.combine(mid_date, datetime.min.time(), tzinfo=tz).replace(hour=12)
    row = row_at(assignment, rows, sample)
    return get_rate(row)


def _emit_common_area_shares(billing_run, accounts_in_scope, tenant_tz, gst_rate) -> None:
    """Apportion common-area meter energy across active child accounts.

    Hierarchical sites only. For each common-area meter, an `internal` billing
    account is auto-created (idempotent), the meter's period-total energy is
    apportioned across active embedded-network tenant accounts by the site's
    `common_area_apportionment_method`, and one `common_area_share` line item is
    written per child (costed at the child's consumption tariff, `source_account`
    linking back to the internal account for audit).
    """
    from apps.readings.models import Stream

    from .models import (
        BillingAccount,
        BillingAccountMeter,
        BillingLineItem,
        BillingRun,
    )

    site = billing_run.site
    if not site.is_hierarchical:
        return

    common_meters = _common_area_meter_devices(site)
    if not common_meters:
        return

    period = billing_run.aggregate_period
    win_start, win_end = billing_run.period_start, billing_run.period_end
    method = site.common_area_apportionment_method

    # Active child (EN tenant) accounts with a grid_import stream, plus each
    # child's period-total import (pro-rata weight) and a representative import
    # stream (for tariff resolution).
    children = []  # (account, import_total, import_stream)
    for account, cstart, cend in accounts_in_scope:
        if account.account_type != BillingAccount.AccountType.EN_TENANT:
            continue
        import_ids = _child_import_stream_ids(
            BillingAccountMeter, account, cstart, cend,
        )
        if not import_ids:
            continue
        import_total = _sum_aggregates_total(import_ids, period, cstart, cend)
        import_stream = Stream.objects.filter(id=import_ids[0]).first()
        children.append((account, import_total, import_stream))

    if not children:
        return

    mid = win_start + (win_end - win_start) / 2
    mid_date = mid.astimezone(ZoneInfo(tenant_tz)).date()

    for device in common_meters:
        internal = _get_or_create_internal_account(billing_run.tenant, device)
        ca_total = _sum_aggregates_total(
            _meter_energy_stream_ids(device), period, win_start, win_end,
        )
        if ca_total <= 0:
            continue

        weights = _apportionment_weights(method, children)
        if sum(weights.values(), Decimal('0')) <= 0:
            continue  # nothing to weight against (e.g. no child consumed)

        shares = _allocate_pool(ca_total, weights)
        for account, _import_total, import_stream in children:
            share = shares.get(account.id, Decimal('0'))
            if share <= 0:
                continue
            rate = _representative_rate(account, import_stream, tenant_tz, mid_date)
            if rate is None:
                raise StepError(
                    BillingRun.Step.COMPUTE_LINE_ITEMS,
                    f'Embedded-network tenant "{account.name}" (id {account.id}) has '
                    f'no consumption tariff to cost its common-area share. Assign a '
                    f'tariff with applies_to_role="consumption".',
                )
            amount = _round_cents(share * rate)
            gst = _round_cents(Decimal(amount) * gst_rate)
            BillingLineItem.objects.create(
                billing_run=billing_run,
                billing_account=account,
                stream=None,
                line_kind=BillingLineItem.LineKind.COMMON_AREA_SHARE,
                period_name='',
                kwh=share.quantize(Decimal('0.000001')),
                rate_cents_per_kwh=rate.quantize(Decimal('0.000001')),
                amount_cents=amount,
                gst_cents=gst,
                quality_summary={},
                source_account=internal,
            )


# ---------------------------------------------------------------------------
# Step — reconcile (Sprint 34, hierarchical sites only)
# ---------------------------------------------------------------------------

def step_reconcile(billing_run) -> None:
    """Compute the energy-balance ReconciliationReport for the run.

    No-op (clears any stale report) for non-hierarchical sites. Runs at draft
    time so the variance is visible before finalize; the finalize gate re-checks
    it. Does not itself block or change run status — it only records the balance.

    input  = gate_import + Σ generation − gate_export
    output = Σ child_grid_import + common_area
    losses = input − output ; variance = |losses| / input × 100
    """
    from apps.metering.models import MeterProfile
    from apps.readings.models import Stream

    from .models import ReconciliationReport

    site = billing_run.site
    with transaction.atomic():
        ReconciliationReport.objects.filter(billing_run=billing_run).delete()
        if not site.is_hierarchical:
            return

        period = billing_run.aggregate_period
        win_start, win_end = billing_run.period_start, billing_run.period_end

        gate_import = _sum_aggregates_total(
            _role_stream_ids(site, MeterProfile.MeterRole.GATE, Stream.BillingRole.GRID_IMPORT),
            period, win_start, win_end,
        )
        gate_export = _sum_aggregates_total(
            _role_stream_ids(site, MeterProfile.MeterRole.GATE, Stream.BillingRole.GRID_EXPORT),
            period, win_start, win_end,
        )
        generation = _sum_aggregates_total(
            _stream_ids_by_role(site, Stream.BillingRole.GENERATION),
            period, win_start, win_end,
        )
        child_import = _sum_aggregates_total(
            _role_stream_ids(site, MeterProfile.MeterRole.CHILD, Stream.BillingRole.GRID_IMPORT),
            period, win_start, win_end,
        )
        common_area = Decimal('0')
        for device in _common_area_meter_devices(site):
            common_area += _sum_aggregates_total(
                _meter_energy_stream_ids(device), period, win_start, win_end,
            )

        input_kwh = gate_import + generation - gate_export
        output_kwh = child_import + common_area
        losses = input_kwh - output_kwh
        if input_kwh > 0:
            variance = (abs(losses) / input_kwh * Decimal('100')).quantize(Decimal('0.0001'))
        else:
            variance = Decimal('0.0000')

        tol = Decimal(str(site.reconciliation_tolerance_percent or 0))
        within = variance <= tol

        ReconciliationReport.objects.create(
            billing_run=billing_run,
            site=site,
            gate_import_kwh=gate_import,
            generation_kwh=generation,
            gate_export_kwh=gate_export,
            child_grid_import_total_kwh=child_import,
            common_area_total_kwh=common_area,
            computed_losses_kwh=losses.quantize(Decimal('0.000001')),
            variance_percent=variance,
            within_tolerance=within,
            status=(
                ReconciliationReport.ReconStatus.OK if within
                else ReconciliationReport.ReconStatus.EXCEEDED
            ),
        )


# ---------------------------------------------------------------------------
# Step 4 — mark_draft
# ---------------------------------------------------------------------------

def step_mark_draft(billing_run) -> None:
    """Transition the run to status=draft + record computed_at."""
    from .models import BillingRun

    billing_run.status = BillingRun.Status.DRAFT
    billing_run.failed_step = None
    billing_run.failure_detail = ''
    billing_run.computed_at = timezone.now()
    billing_run.save(update_fields=[
        'status', 'failed_step', 'failure_detail', 'computed_at',
    ])


STEP_DISPATCH = None  # populated below to avoid forward-reference issues


def _build_dispatch():
    """Return the {Step → callable} map. Built lazily to avoid import order."""
    from .models import BillingRun

    return {
        BillingRun.Step.RESOLVE_SCOPE: step_resolve_scope,
        BillingRun.Step.SNAPSHOT: step_snapshot,
        BillingRun.Step.ALLOCATE_SOLAR: step_allocate_solar,
        BillingRun.Step.COMPUTE_LINE_ITEMS: step_compute_line_items,
        BillingRun.Step.RECONCILE: step_reconcile,
        BillingRun.Step.MARK_DRAFT: step_mark_draft,
    }


def _ensure_dispatch():
    global STEP_DISPATCH
    if STEP_DISPATCH is None:
        STEP_DISPATCH = _build_dispatch()
    return STEP_DISPATCH


def run_pipeline(billing_run, from_step=None) -> None:
    """Execute the engine steps in order, optionally starting from ``from_step``.

    Raises StepError if a step fails. The caller maps that to BillingRun
    status=failed + failed_step + failure_detail on the model.
    """
    from .models import BillingRun

    dispatch = _ensure_dispatch()
    steps = (
        BillingRun.Step.RESOLVE_SCOPE,
        BillingRun.Step.SNAPSHOT,
        BillingRun.Step.ALLOCATE_SOLAR,
        BillingRun.Step.COMPUTE_LINE_ITEMS,
        BillingRun.Step.RECONCILE,
        BillingRun.Step.MARK_DRAFT,
    )
    start_idx = steps.index(from_step) if from_step else 0

    for step in steps[start_idx:]:
        try:
            dispatch[step](billing_run)
        except StepError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StepError(step, str(exc)) from exc

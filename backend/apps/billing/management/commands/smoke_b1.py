"""Phase B1 sign-off smoke checks — repeatable.

Drives the real derived-stream dispatch, interval aggregator, windowed-rule
evaluator, and hierarchical meter-profile invariants against the running stack
(Postgres + Redis). Every scenario runs inside a rolled-back savepoint, so the
command is safe to re-run and leaves no data behind.

    docker-compose run --rm --no-deps backend python manage.py smoke_b1

Exits non-zero if any check fails.

Covers the ROADMAP Phase B1 sign-off checklist (manual smoke tests):
  * delta derived stream → interval kWh values
  * cross-device consumption_from_solar → auto-created site-composite Device
  * 5m / 30m / 1h / 1d / 1mo aggregates maintained (+ idempotent, + beat-wired)
  * windowed-aggregate rule (avg > 30 over 15 min) fires / doesn't fire
  * hierarchical-site invariants (gate + children + common area)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.readings.aggregates import clock_align, compute_aggregate
from apps.readings.derived_dispatch import (
    evaluate_derived_stream,
    sources_span_multiple_devices,
)
from apps.readings.models import (
    DerivedStream,
    IntervalAggregate,
    Stream,
    StreamReading,
)
from apps.rules.evaluator import _eval_windowed_aggregate_condition
from apps.rules.models import Rule, RuleCondition, RuleConditionGroup

from ._smoke_util import (
    Reporter,
    auth_client,
    disable_mqtt_provisioning,
    make_admin,
    make_device,
    make_site,
    make_stream,
    make_tenant,
    scenario,
)

# A fixed base instant, safely in the past (all buckets complete).
BASE = datetime(2026, 5, 1, 10, 0, tzinfo=dt_timezone.utc)


def _ts(minutes=0, hours=0):
    return BASE + timedelta(hours=hours, minutes=minutes)


class Command(BaseCommand):
    help = 'Run the Phase B1 sign-off smoke checks (repeatable, non-destructive).'

    def handle(self, *args, **options):
        reporter = Reporter(self.stdout, self.style)
        disable_mqtt_provisioning()
        self.stdout.write(self.style.MIGRATE_HEADING('Phase B1 sign-off smoke checks'))

        # One outer transaction; every scenario savepoint-rolls-back inside it,
        # and we roll the whole thing back at the end so nothing persists.
        class _RollbackAll(Exception):
            pass

        try:
            with transaction.atomic():
                self._derived_delta(reporter)
                self._cross_device_composite(reporter)
                self._aggregates(reporter)
                self._windowed_rule(reporter)
                self._hierarchical_invariants(reporter)
                raise _RollbackAll
        except _RollbackAll:
            pass

        reporter.summarize()
        if reporter.fail_count:
            raise CommandError(f'{reporter.fail_count} B1 check(s) failed.')

    # -- delta derived stream ------------------------------------------------

    def _derived_delta(self, reporter):
        with scenario(reporter, 'delta derived stream → interval kWh'):
            tenant = make_tenant()
            site = make_site(tenant)
            device = make_device(tenant, site, 'B1-DELTA')
            source = make_stream(device, key='cumulative_kwh')
            output = Stream.objects.create(
                device=device, key='interval_kwh',
                data_type=Stream.DataType.NUMERIC,
                stream_type=Stream.StreamType.DERIVED,
            )
            derived = DerivedStream.objects.create(stream=output, formula='delta')
            derived.source_streams.set([source])

            StreamReading.objects.create(stream=source, value=100.0, timestamp=_ts(0))
            StreamReading.objects.create(stream=source, value=150.0, timestamp=_ts(5))
            evaluate_derived_stream(derived.pk, source.pk)

            rows = list(StreamReading.objects.filter(stream=output).order_by('timestamp'))
            reporter.check(
                'delta produces exactly one interval reading',
                len(rows) == 1, f'got {len(rows)}',
            )
            if rows:
                reporter.check(
                    'delta value = 150 − 100 = 50',
                    float(rows[0].value) == 50.0, f'got {rows[0].value}',
                )
                reporter.check(
                    'interval stamped at later reading',
                    rows[0].timestamp == _ts(5),
                )

            # A counter reset (value drops) must not emit a negative interval.
            StreamReading.objects.create(stream=source, value=10.0, timestamp=_ts(10))
            evaluate_derived_stream(derived.pk, source.pk)
            negatives = StreamReading.objects.filter(stream=output, value__lt=0).count()
            reporter.check('counter reset drops cleanly (no negative)', negatives == 0)

    # -- cross-device site composite ----------------------------------------

    def _cross_device_composite(self, reporter):
        with scenario(reporter, 'cross-device consumption_from_solar → site composite'):
            tenant = make_tenant()
            site = make_site(tenant)
            admin = make_admin(tenant)
            dev_a = make_device(tenant, site, 'B1-GEN')
            dev_b = make_device(tenant, site, 'B1-EXP')
            gen = make_stream(dev_a, key='gen')
            exp = make_stream(dev_b, key='export')

            reporter.check(
                'sources span multiple devices',
                sources_span_multiple_devices([gen, exp]) is True,
            )
            # No composite device before first cross-device use.
            existed = Stream.objects.filter(
                device__site=site, device__is_virtual=True,
            ).exists()

            resp = auth_client(admin).post(
                '/api/v1/derived-streams/',
                {
                    'key': 'consumption_from_solar', 'unit': 'kWh',
                    'formula': 'difference',
                    'source_stream_ids': [gen.pk, exp.pk],
                },
                format='json',
            )
            ok = reporter.check(
                'derived-stream API accepts cross-device difference (201)',
                resp.status_code == 201, f'status {resp.status_code}',
            )
            if ok:
                from apps.devices.models import Device
                data = resp.json()
                host_dev = Device.objects.get(pk=data['stream_device_id'])
                reporter.check(
                    'host Device is virtual',
                    host_dev.is_virtual is True,
                )
                reporter.check(
                    'host Device is the site-composite type',
                    host_dev.device_type.slug == 'site-composite',
                    host_dev.device_type.slug,
                )
                reporter.check(
                    'site composite auto-created (did not exist before)',
                    existed is False and host_dev.site_id == site.pk,
                )

    # -- interval aggregates -------------------------------------------------

    def _aggregates(self, reporter):
        with scenario(reporter, '5m / 30m / 1h / 1d / 1mo interval aggregates'):
            tenant = make_tenant()
            site = make_site(tenant)
            device = make_device(tenant, site, 'B1-AGG')
            stream = make_stream(device, key='power_kwh')

            # Readings across a 24h window; sums are chosen to be distinct per period.
            for ts, val in [
                (_ts(0), 2.0),     # 10:00
                (_ts(3), 3.0),     # 10:03  → 5m[10:00] = 5
                (_ts(20), 1.0),    # 10:20  → 30m[10:00] = 6
                (_ts(45), 4.0),    # 10:45  → 1h[10:00]  = 10
                (_ts(0, hours=5), 90.0),  # 15:00 → 1d/1mo = 100
            ]:
                StreamReading.objects.create(stream=stream, value=val, timestamp=ts)

            expectations = [
                (IntervalAggregate.Period.MIN_5, _ts(3), 5.0),
                (IntervalAggregate.Period.MIN_30, _ts(20), 6.0),
                (IntervalAggregate.Period.HOUR, _ts(45), 10.0),
                (IntervalAggregate.Period.DAY, _ts(0, hours=5), 100.0),
                (IntervalAggregate.Period.MONTH, _ts(0, hours=5), 100.0),
            ]
            for period, in_bucket, expected in expectations:
                aligned = clock_align(in_bucket, period)
                agg = compute_aggregate(stream, period, aligned, Stream.AggregationKind.SUM)
                reporter.check(
                    f'{period} aggregate sum = {expected}',
                    float(agg.value) == expected, f'got {agg.value}',
                )

            # Idempotency: recompute the daily bucket → same single row, same value.
            aligned_day = clock_align(_ts(0, hours=5), IntervalAggregate.Period.DAY)
            compute_aggregate(stream, IntervalAggregate.Period.DAY, aligned_day,
                              Stream.AggregationKind.SUM)
            day_rows = IntervalAggregate.objects.filter(
                stream=stream, period=IntervalAggregate.Period.DAY,
                period_start=aligned_day, aggregation_kind='sum',
            )
            reporter.check(
                'aggregator idempotent on re-run (one row, update_or_create)',
                day_rows.count() == 1 and float(day_rows.first().value) == 100.0,
            )

            # Automation: the beat schedule wires the maintenance task.
            tasks = {v.get('task') for v in settings.CELERY_BEAT_SCHEDULE.values()}
            reporter.check(
                'maintain_interval_aggregates registered in CELERY_BEAT_SCHEDULE',
                'readings.maintain_interval_aggregates' in tasks,
            )

    # -- windowed aggregate rule --------------------------------------------

    def _windowed_rule(self, reporter):
        with scenario(reporter, 'windowed-aggregate rule (avg > 30 over 15 min)'):
            from django.utils import timezone

            tenant = make_tenant()
            site = make_site(tenant)
            device = make_device(tenant, site, 'B1-RULE')
            stream = make_stream(device, key='temperature', unit='°C')

            rule = Rule.objects.create(tenant=tenant, name='avg temp > 30', is_active=True)
            group = RuleConditionGroup.objects.create(rule=rule, logical_operator='AND')
            cond = RuleCondition.objects.create(
                group=group,
                condition_type=RuleCondition.ConditionType.WINDOWED_AGGREGATE,
                stream=stream, aggregate_fn='avg', window_minutes=15,
                operator='>', threshold_value='30',
            )

            now = timezone.now()
            for mins, val in [(10, 28.0), (5, 34.0), (1, 40.0)]:  # avg = 34 > 30
                StreamReading.objects.create(
                    stream=stream, value=val, timestamp=now - timedelta(minutes=mins),
                )
            reporter.check(
                'fires when rolling avg (34.0) crosses 30',
                _eval_windowed_aggregate_condition(cond) is True,
            )

            # Below threshold → does not fire.
            cool = Rule.objects.create(tenant=tenant, name='avg > 30 (cool)', is_active=True)
            cg = RuleConditionGroup.objects.create(rule=cool, logical_operator='AND')
            cc = RuleCondition.objects.create(
                group=cg,
                condition_type=RuleCondition.ConditionType.WINDOWED_AGGREGATE,
                stream=stream, aggregate_fn='avg', window_minutes=15,
                operator='>', threshold_value='30',
            )
            s2 = make_stream(make_device(tenant, site, 'B1-RULE2'), key='t2')
            cc.stream = s2
            cc.save()
            StreamReading.objects.create(stream=s2, value=20.0, timestamp=now - timedelta(minutes=2))
            reporter.check(
                'does not fire when avg (20.0) below 30',
                _eval_windowed_aggregate_condition(cc) is False,
            )

    # -- hierarchical meter-profile invariants ------------------------------

    def _hierarchical_invariants(self, reporter):
        with scenario(reporter, 'hierarchical-site invariants (gate + children + common area)'):
            tenant = make_tenant()
            site = make_site(tenant, hierarchical=True, name='EN Site')
            admin = make_admin(tenant)
            client = auth_client(admin)

            gate = make_device(tenant, site, 'B1-GATE')
            child1 = make_device(tenant, site, 'B1-CH1')
            child2 = make_device(tenant, site, 'B1-CH2')
            child3 = make_device(tenant, site, 'B1-CH3')
            common = make_device(tenant, site, 'B1-CA')

            def mp_url(dev):
                return f'/api/v1/devices/{dev.id}/meter-profile/'

            # Gate meter (no parent).
            r = client.put(mp_url(gate), {'meter_role': 'gate'}, format='json')
            reporter.check('gate meter accepted', r.status_code in (200, 201),
                           f'status {r.status_code}')

            # Child without parent on hierarchical site → rejected.
            r = client.put(mp_url(child1), {'meter_role': 'child'}, format='json')
            reporter.check('child without parent rejected (400)',
                           r.status_code == 400, f'status {r.status_code}')

            # Three children + common area with the gate as parent → accepted.
            accepted = 0
            for dev in (child1, child2, child3):
                r = client.put(
                    mp_url(dev),
                    {'meter_role': 'child', 'parent_meter': gate.id},
                    format='json',
                )
                if r.status_code in (200, 201):
                    accepted += 1
            reporter.check('3 children accepted with gate parent', accepted == 3,
                           f'{accepted}/3')

            r = client.put(
                mp_url(common),
                {'meter_role': 'common_area', 'parent_meter': gate.id},
                format='json',
            )
            reporter.check('common-area meter accepted', r.status_code in (200, 201),
                           f'status {r.status_code}')

            # A second gate on the same site → rejected (at most one gate v1).
            r = client.put(mp_url(child1), {'meter_role': 'gate'}, format='json')
            reporter.check('second gate on the site rejected (400)',
                           r.status_code == 400, f'status {r.status_code}')

            # Reconciliation tolerance is settable on the hierarchical site.
            site.reconciliation_tolerance_percent = 1.5
            site.save(update_fields=['reconciliation_tolerance_percent'])
            site.refresh_from_db()
            reporter.check(
                'reconciliation tolerance set on site',
                float(site.reconciliation_tolerance_percent) == 1.5,
            )

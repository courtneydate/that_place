"""Rule evaluation engine for That Place.

Core logic for evaluating a Rule's condition groups against live data and
determining whether the rule should fire, stay suppressed, or clear.

Entry point: ``run_evaluation(rule)`` — returns an ``EvaluationResult``.

Condition types handled:
  stream          — compares the latest StreamReading value against a threshold
  staleness       — deferred to Sprint 17 (beat task); treated as False here
  feed_channel    — compares the latest FeedReading value against a threshold
  reference_value — resolves the current dataset row value and compares

Stale stream policy (SPEC.md § Open Questions — resolved):
  If a stream has never reported (no StreamReading exists), the condition
  evaluates to False. The last known value is used for streams that have
  reported at least once, regardless of how recently.

Redis lock (SPEC.md § Feature: Rule Evaluation Engine — concurrency safety):
  SET NX with a 5-minute TTL prevents two simultaneous workers both firing
  the same false→true transition. If Redis is unavailable the lock is skipped
  (fail open) — a duplicate firing is preferable to silently missing an event.

Ref: SPEC.md § Feature: Rules Engine, § Feature: Rule Evaluation Engine
     SPEC.md § Open Questions — unknown condition state (resolved: stale = false)
"""
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

import redis
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_REDIS_LOCK_TTL = 300  # seconds — TTL is a crash-recovery backstop only


# ---------------------------------------------------------------------------
# Redis lock helpers
# ---------------------------------------------------------------------------

def _redis_lock_key(rule_id: int) -> str:
    """Return the Redis key used for the evaluation lock on a rule."""
    return f'rule:{rule_id}:eval_lock'


def _try_acquire_lock(rule_id: int) -> bool:
    """Attempt to atomically acquire the evaluation lock (SET NX).

    Returns True if this worker wins the lock (should fire).
    Returns False if another worker already holds it (should skip).
    Fails open — returns True — if Redis is unreachable.
    """
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL, decode_responses=True, socket_connect_timeout=2
        )
        result = client.set(_redis_lock_key(rule_id), '1', nx=True, ex=_REDIS_LOCK_TTL)
        return result is True
    except Exception:
        logger.warning(
            'Redis unavailable for rule %d eval lock — proceeding without lock (fail open)',
            rule_id,
        )
        return True


def _release_lock(rule_id: int) -> None:
    """Delete the evaluation lock after a successful DB write.

    Failure is non-fatal — the key will auto-expire via TTL.
    """
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL, decode_responses=True, socket_connect_timeout=2
        )
        client.delete(_redis_lock_key(rule_id))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Schedule gate
# ---------------------------------------------------------------------------

def within_schedule_gate(rule, now_utc) -> bool:
    """Return True if ``now`` falls within the rule's schedule gate.

    If no gate is configured (all gate fields are None) the rule may fire at
    any time. The gate is evaluated in the tenant's IANA timezone.

    Day and time restrictions are independent — both must be satisfied if set.
    A midnight-wrapping time window (active_from > active_to) is handled
    correctly, e.g. 22:00–06:00.

    Ref: SPEC.md § Feature: Rules Engine — Schedule gate
    """
    has_day_gate = bool(rule.active_days)
    has_time_gate = rule.active_from is not None or rule.active_to is not None

    if not has_day_gate and not has_time_gate:
        return True

    tz_name = getattr(rule.tenant, 'timezone', None) or 'Australia/Sydney'
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)

    if has_day_gate:
        # Python weekday(): 0=Mon … 6=Sun, same as SPEC
        if now_local.weekday() not in rule.active_days:
            return False

    if has_time_gate:
        current_time = now_local.time().replace(second=0, microsecond=0)
        active_from = rule.active_from
        active_to = rule.active_to

        if active_from and active_to:
            if active_from <= active_to:
                # Normal window: 08:00 – 18:00
                if not (active_from <= current_time < active_to):
                    return False
            else:
                # Wraps midnight: 22:00 – 06:00
                if not (current_time >= active_from or current_time < active_to):
                    return False
        elif active_from:
            if current_time < active_from:
                return False
        elif active_to:
            if current_time >= active_to:
                return False

    return True


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def evaluate_conditions(rule) -> bool:
    """Evaluate all condition groups for a rule and return the overall result.

    Groups are combined using rule.condition_group_operator (AND/OR).
    Each group's conditions are combined using the group's logical_operator (AND/OR).
    An empty rule (no groups) evaluates to False.
    """
    groups = list(
        rule.condition_groups
        .prefetch_related(
            'conditions',
            'conditions__stream',
            'conditions__channel',
            'conditions__dataset',
        )
    )

    if not groups:
        return False

    group_results = [_evaluate_group(group, rule) for group in groups]

    if rule.condition_group_operator == 'AND':
        return all(group_results)
    return any(group_results)


def _evaluate_group(group, rule) -> bool:
    """Evaluate all conditions within a single condition group."""
    conditions = list(group.conditions.all())

    if not conditions:
        return False

    results = [_evaluate_condition(condition, rule) for condition in conditions]

    if group.logical_operator == 'AND':
        return all(results)
    return any(results)


def _evaluate_condition(condition, rule) -> bool:
    """Dispatch to the appropriate condition type evaluator."""
    from .models import RuleCondition

    ct = condition.condition_type

    if ct == RuleCondition.ConditionType.STREAM:
        return _eval_stream_condition(condition)
    if ct == RuleCondition.ConditionType.STALENESS:
        return _eval_staleness_condition(condition)
    if ct == RuleCondition.ConditionType.FEED_CHANNEL:
        return _eval_feed_channel_condition(condition)
    if ct == RuleCondition.ConditionType.REFERENCE_VALUE:
        return _eval_reference_value_condition(condition, rule)

    logger.warning('Unknown condition type "%s" on condition %d', ct, condition.pk)
    return False


def _eval_stream_condition(condition) -> bool:
    """Evaluate a stream point-in-time condition.

    Uses the latest StreamReading for the referenced stream. If no reading
    exists (stream has never reported), returns False per the resolved stale
    stream policy.

    Ref: SPEC.md § Open Questions — unknown condition state (resolved)
    """
    from apps.readings.models import StreamReading

    if condition.stream_id is None:
        return False

    reading = (
        StreamReading.objects
        .filter(stream_id=condition.stream_id)
        .order_by('-timestamp')
        .values('value')
        .first()
    )
    if reading is None:
        return False

    return _compare(
        reading['value'],
        condition.operator,
        condition.threshold_value,
        condition.stream.data_type,
    )


def _eval_staleness_condition(condition) -> bool:
    """Evaluate a staleness condition.

    Returns True (condition met — rule should fire) when the stream has not
    reported a reading within ``condition.staleness_minutes`` minutes.

    A stream that has never reported is considered stale (returns True).
    Clearing happens automatically: when a new reading arrives the ingestion
    path dispatches evaluate_rule via RuleStreamIndex, and this function then
    returns False (stream is fresh), triggering a true→false clear.

    Ref: SPEC.md § Feature: Rules Engine — staleness conditions
         SPEC.md § Feature: Rule Evaluation Engine — Sprint 17
    """
    from apps.readings.models import StreamReading

    if condition.stream_id is None or not condition.staleness_minutes:
        return False

    latest = (
        StreamReading.objects
        .filter(stream_id=condition.stream_id)
        .order_by('-timestamp')
        .values('timestamp')
        .first()
    )

    if latest is None:
        # Stream has never reported — treat as stale
        return True

    stale_after = timezone.now() - timedelta(minutes=condition.staleness_minutes)
    return latest['timestamp'] < stale_after


def _eval_feed_channel_condition(condition) -> bool:
    """Evaluate a feed channel condition against the latest FeedReading.

    Feed channel conditions are numeric only.
    """
    from apps.feeds.models import FeedReading

    if condition.channel_id is None:
        return False

    reading = (
        FeedReading.objects
        .filter(channel_id=condition.channel_id)
        .order_by('-timestamp')
        .values('value')
        .first()
    )
    if reading is None:
        return False

    return _compare(reading['value'], condition.operator, condition.threshold_value, 'numeric')


def _eval_reference_value_condition(condition, rule) -> bool:
    """Evaluate a reference_value condition by resolving the dataset assignment.

    Looks up the tenant-wide TenantDatasetAssignment for this rule's tenant
    and condition's dataset. Site-specific resolution requires knowing the
    triggering site, which is not available in the current evaluation context;
    tenant-wide assignments are used for Sprint 16.

    dimension_overrides from the condition are merged over the assignment's
    dimension_filter before resolution.
    """
    from apps.feeds.models import TenantDatasetAssignment
    from apps.feeds.resolution import ResolutionError, resolve_dataset_assignment

    if condition.dataset_id is None or not condition.value_key:
        return False

    today = timezone.now().date()

    try:
        assignment = (
            TenantDatasetAssignment.objects
            .select_related('dataset', 'tenant')
            .get(
                tenant=rule.tenant,
                dataset_id=condition.dataset_id,
                site=None,
                effective_from__lte=today,
            )
        )
        # Exclude expired assignments
        if assignment.effective_to and assignment.effective_to < today:
            return False
    except TenantDatasetAssignment.DoesNotExist:
        logger.debug(
            'No active tenant-wide TenantDatasetAssignment for dataset %d, rule %d',
            condition.dataset_id, condition.group.rule_id,
        )
        return False
    except TenantDatasetAssignment.MultipleObjectsReturned:
        logger.warning(
            'Multiple tenant-wide assignments for dataset %d on tenant %d — '
            'cannot resolve unambiguously for rule %d',
            condition.dataset_id, rule.tenant_id, condition.group.rule_id,
        )
        return False

    try:
        resolved = resolve_dataset_assignment(assignment, condition.dimension_overrides)
    except ResolutionError as exc:
        logger.warning(
            'Reference value resolution failed for rule %d condition %d: %s',
            rule.pk, condition.pk, exc,
        )
        return False

    value = resolved.get(condition.value_key)
    if value is None:
        logger.warning(
            'value_key "%s" not found in resolved dataset for rule %d',
            condition.value_key, rule.pk,
        )
        return False

    return _compare(value, condition.operator, condition.threshold_value, 'numeric')


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _compare(value, operator: str, threshold: str, data_type: str) -> bool:
    """Compare a reading value against a threshold string using the given operator.

    Numeric and string coercion follows the stream's data_type.
    Returns False on any coercion error.
    """
    try:
        if data_type == 'numeric':
            lhs = float(value)
            rhs = float(threshold)
        elif data_type == 'boolean':
            lhs = str(value).lower() in ('true', '1', 'yes')
            rhs = str(threshold).lower() in ('true', '1', 'yes')
        else:  # string / enum
            lhs = str(value)
            rhs = str(threshold)
    except (TypeError, ValueError):
        logger.warning(
            'Type coercion failed: value=%r threshold=%r data_type=%s operator=%s',
            value, threshold, data_type, operator,
        )
        return False

    if operator == '>':
        return lhs > rhs
    if operator == '<':
        return lhs < rhs
    if operator == '>=':
        return lhs >= rhs
    if operator == '<=':
        return lhs <= rhs
    if operator == '==':
        return lhs == rhs
    if operator == '!=':
        return lhs != rhs

    logger.warning('Unknown operator "%s"', operator)
    return False


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_evaluation(rule, now=None) -> str:
    """Evaluate a rule and apply state transitions.

    Returns a string describing the outcome:
      'fired'       — false→true transition; rule fired
      'suppressed'  — true→true; rule already in triggered state
      'cleared'     — true→false; rule state cleared
      'no_change'   — false→false; nothing happened
      'cooldown'    — false→true conditions met but cooldown prevents firing
      'gate_blocked'— false→true conditions met but schedule gate is closed
      'lock_lost'   — false→true conditions met but another worker won the Redis lock

    Separating this from the Celery task makes the logic easy to unit-test
    without mocking Celery internals.

    Ref: SPEC.md § Feature: Rule Evaluation Engine
    """
    from .models import Rule

    if now is None:
        now = timezone.now()

    new_state = evaluate_conditions(rule)

    # Schedule gate — only blocks false→true firing, not state clearing
    if new_state and not within_schedule_gate(rule, now):
        # Conditions are true but gate is closed — treat as false for firing purposes
        if rule.current_state:
            # true→false (gate closed while conditions true): leave state as-is
            # Clearing only happens when conditions genuinely go false
            return 'gate_blocked'
        return 'gate_blocked'

    old_state = rule.current_state

    if not old_state and new_state:
        # false → true: check cooldown, acquire lock, fire
        if rule.cooldown_minutes and rule.last_fired_at:
            cooldown_until = rule.last_fired_at + timedelta(minutes=rule.cooldown_minutes)
            if now < cooldown_until:
                logger.debug(
                    'Rule %d in cooldown until %s — skipping fire', rule.pk, cooldown_until
                )
                return 'cooldown'

        if not _try_acquire_lock(rule.pk):
            logger.debug('Rule %d lock not acquired — another worker won', rule.pk)
            return 'lock_lost'

        try:
            Rule.objects.filter(pk=rule.pk).update(
                current_state=True,
                last_fired_at=now,
            )
            # Keep in-memory instance consistent
            rule.current_state = True
            rule.last_fired_at = now
            logger.info('Rule %d fired (false→true) at %s', rule.pk, now)
        finally:
            _release_lock(rule.pk)

        return 'fired'

    if old_state and not new_state:
        # true → false: clear state
        Rule.objects.filter(pk=rule.pk).update(current_state=False)
        rule.current_state = False
        logger.info('Rule %d cleared (true→false)', rule.pk)
        return 'cleared'

    if old_state and new_state:
        logger.debug('Rule %d suppressed (true→true)', rule.pk)
        return 'suppressed'

    return 'no_change'

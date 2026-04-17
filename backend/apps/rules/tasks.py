"""Celery tasks for the rules evaluation engine.

Sprint 16: Rule Evaluation Engine.
Sprint 17: Staleness beat task.

evaluate_rule(rule_id) — looks up the rule, runs the full evaluation via
    evaluator.run_evaluation(), and handles the state transition. Called by:
    - ingestion.dispatch_stream_rule_evaluation  (on each new StreamReading)
    - feeds._dispatch_feed_rule_evaluation        (on each new FeedReading)
    - feeds.evaluate_reference_value_rules        (beat task, every 5 min)
    - rules.evaluate_staleness_rules              (beat task, every 60 s)

evaluate_staleness_rules() — beat task, every 60 s. Finds all active rules
    that have at least one staleness condition and dispatches evaluate_rule
    for each, so staleness fires within one beat interval of the threshold
    being exceeded.

Ref: SPEC.md § Feature: Rule Evaluation Engine
     SPEC.md § Feature: Rules Engine — staleness conditions
"""
import logging

from celery import shared_task
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(name='rules.evaluate_rule')
def evaluate_rule(rule_id: int) -> str | None:
    """Evaluate a single rule and apply the resulting state transition.

    Loads the rule with all required relations in a single query, then
    delegates to evaluator.run_evaluation() for the core logic.

    Returns the outcome string from run_evaluation() ('fired', 'suppressed',
    'cleared', 'no_change', etc.), or None if the rule is not found / inactive.

    The transaction wraps only the DB write in run_evaluation — reads are
    intentionally outside the transaction to avoid long-held locks during
    the Redis NX check.

    Ref: SPEC.md § Feature: Rule Evaluation Engine
    """
    from .evaluator import run_evaluation
    from .models import Rule

    try:
        rule = (
            Rule.objects
            .select_related('tenant')
            .prefetch_related(
                'condition_groups',
                'condition_groups__conditions',
                'condition_groups__conditions__stream',
                'condition_groups__conditions__channel',
                'condition_groups__conditions__dataset',
            )
            .get(pk=rule_id, is_active=True)
        )
    except Rule.DoesNotExist:
        logger.debug('evaluate_rule: rule %d not found or inactive — skipping', rule_id)
        return None

    with transaction.atomic():
        outcome = run_evaluation(rule)
        if outcome == 'fired':
            from apps.alerts.models import Alert
            Alert.objects.create(
                rule=rule,
                tenant=rule.tenant,
                triggered_at=rule.last_fired_at,
                status=Alert.Status.ACTIVE,
            )

    logger.debug('evaluate_rule: rule %d → %s', rule_id, outcome)
    return outcome


@shared_task(name='rules.evaluate_staleness_rules')
def evaluate_staleness_rules() -> None:
    """Dispatch evaluate_rule for every active rule that has a staleness condition.

    Runs every 60 seconds via Celery beat. This is the trigger that causes
    staleness conditions to fire within one beat interval of the threshold
    being exceeded.

    Clearing happens automatically via the ingestion path: when a new
    StreamReading arrives, _dispatch_stream_rule_evaluation fires evaluate_rule
    which re-evaluates the staleness condition as False (stream is fresh),
    triggering a true→false state clear.

    Uses a direct scan of RuleCondition (no separate index) — equivalent to
    the evaluate_reference_value_rules pattern. The result set is bounded by
    the number of active staleness conditions, which is small in practice.

    Ref: SPEC.md § Feature: Rules Engine — staleness conditions (Sprint 17)
    """
    from .models import RuleCondition

    rule_ids = set(
        RuleCondition.objects
        .filter(
            condition_type=RuleCondition.ConditionType.STALENESS,
            group__rule__is_active=True,
        )
        .values_list('group__rule_id', flat=True)
    )

    for rule_id in rule_ids:
        evaluate_rule.delay(rule_id)

    logger.debug(
        'evaluate_staleness_rules: dispatched %d rule evaluation task(s)',
        len(rule_ids),
    )

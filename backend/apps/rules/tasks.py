"""Celery tasks for the rules evaluation engine.

Sprint 16: Rule Evaluation Engine.

evaluate_rule(rule_id) — looks up the rule, runs the full evaluation via
    evaluator.run_evaluation(), and handles the state transition. Called by:
    - ingestion.dispatch_stream_rule_evaluation  (on each new StreamReading)
    - feeds._dispatch_feed_rule_evaluation        (on each new FeedReading)
    - feeds.evaluate_reference_value_rules        (beat task, every 5 min)

Ref: SPEC.md § Feature: Rule Evaluation Engine
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

    logger.debug('evaluate_rule: rule %d → %s', rule_id, outcome)
    return outcome

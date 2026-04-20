"""MQTT topic router for the That Place ingestion pipeline.

Implements a registered-pattern system that parses incoming MQTT topics into
structured ParsedTopic objects. Patterns are registered at module load time
and matched in registration order — more specific patterns should be registered
first.

Supported formats
-----------------
Legacy v1  — ``fm/mm/{unit_serial}/{message_type}``
             unit_serial == device_serial (the Scout IS the device in v1)

That Place v1 Scout telemetry — ``that-place/scout/{scout_serial}/telemetry``
             Scout's own health/status telemetry; scout_serial == device_serial

That Place v1 device telemetry — ``that-place/scout/{scout_serial}/{device_serial}/telemetry``
             Telemetry from a device bridged through a Scout.

Ref: SPEC.md § Feature: MQTT Topic Router
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedTopic:
    """The result of a successful topic match.

    Attributes
    ----------
    pattern_name:  Identifier of the registered pattern that matched.
    scout_serial:  Serial number of the Scout (gateway) that sent the message.
    device_serial: Serial number of the target device.
                   Equals scout_serial for v1 topics and v2 Scout-only telemetry.
    message_type:  What kind of payload this is (e.g. 'telemetry', 'weatherstation').
    topic_format:  'legacy_v1' or 'that_place_v1' — used to update Device.topic_format (DB enum value).
    """

    pattern_name: str
    scout_serial: str
    device_serial: str
    message_type: str
    topic_format: str


@dataclass(frozen=True)
class TopicPattern:
    """A registered topic pattern.

    Attributes
    ----------
    name:         Unique identifier for this pattern.
    regex:        Compiled regular expression. Named groups ``scout`` and
                  optionally ``device`` are extracted from the match.
    topic_format: Value written to ``Device.topic_format`` on match.
    message_type: Value written to ``ParsedTopic.message_type``.
    has_device:   True when the pattern contains a separate device serial
                  distinct from the scout serial (v2 bridged devices only).
    """

    name: str
    regex: re.Pattern
    topic_format: str
    message_type: str
    has_device: bool = False


class TopicRouter:
    """Registry of MQTT topic patterns with ordered matching.

    Usage::

        router = TopicRouter()
        router.register(TopicPattern(...))
        result = router.route('fm/mm/UNIT123/telemetry')
        # result.device_serial == 'UNIT123'
    """

    def __init__(self) -> None:
        """Initialise with an empty pattern list."""
        self._patterns: List[TopicPattern] = []

    def register(self, pattern: TopicPattern) -> None:
        """Add a pattern to the registry.

        Patterns are matched in registration order; register more-specific
        patterns before more-general ones.
        """
        self._patterns.append(pattern)
        logger.debug('Registered MQTT topic pattern: %s (%s)', pattern.name, pattern.regex.pattern)

    def route(self, topic: str) -> Optional[ParsedTopic]:
        """Attempt to match *topic* against registered patterns.

        Returns a :class:`ParsedTopic` on the first match, or ``None`` if no
        pattern matches.
        """
        # Strip a leading slash — some legacy units publish with one
        normalised = topic.lstrip('/')

        for pattern in self._patterns:
            match = pattern.regex.match(normalised)
            if match is None:
                continue

            scout_serial = match.group('scout')
            device_serial = match.group('device') if pattern.has_device else scout_serial

            return ParsedTopic(
                pattern_name=pattern.name,
                scout_serial=scout_serial,
                device_serial=device_serial,
                message_type=pattern.message_type,
                topic_format=pattern.topic_format,
            )

        return None


# ---------------------------------------------------------------------------
# Singleton router — patterns registered at module load time
# ---------------------------------------------------------------------------

router = TopicRouter()

# --- That Place v1: Scout own telemetry (more specific — registered first) ---
# Topic: that-place/scout/{scout_serial}/telemetry
# The Scout publishes its own 12-variable CSV telemetry on this topic.
router.register(TopicPattern(
    name='that_place_v1_scout_telemetry',
    regex=re.compile(r'^that-place/scout/(?P<scout>[^/]+)/telemetry$'),
    topic_format='that_place_v1',
    message_type='scout_telemetry',
    has_device=False,
))

# --- That Place v1: device telemetry bridged through Scout ---
# Topic: that-place/scout/{scout_serial}/{device_serial}/telemetry
router.register(TopicPattern(
    name='that_place_v1_device_telemetry',
    regex=re.compile(r'^that-place/scout/(?P<scout>[^/]+)/(?P<device>[^/]+)/telemetry$'),
    topic_format='that_place_v1',
    message_type='telemetry',
    has_device=True,
))

# --- Legacy v1: general telemetry ---
# Topic: fm/mm/{unit_serial}/telemetry
router.register(TopicPattern(
    name='legacy_v1_telemetry',
    regex=re.compile(r'^fm/mm/(?P<scout>[^/]+)/telemetry$'),
    topic_format='legacy_v1',
    message_type='telemetry',
    has_device=False,
))

# --- Legacy v1: weather station ---
# Topic: fm/mm/{unit_serial}/weatherstation
router.register(TopicPattern(
    name='legacy_v1_weatherstation',
    regex=re.compile(r'^fm/mm/(?P<scout>[^/]+)/weatherstation$'),
    topic_format='legacy_v1',
    message_type='weatherstation',
    has_device=False,
))

# --- Legacy v1: TBox ---
# Topic: fm/mm/{unit_serial}/tbox
router.register(TopicPattern(
    name='legacy_v1_tbox',
    regex=re.compile(r'^fm/mm/(?P<scout>[^/]+)/tbox$'),
    topic_format='legacy_v1',
    message_type='tbox',
    has_device=False,
))

# --- Legacy v1: ABB Drive ---
# Topic: fm/mm/{unit_serial}/abb
router.register(TopicPattern(
    name='legacy_v1_abb',
    regex=re.compile(r'^fm/mm/(?P<scout>[^/]+)/abb$'),
    topic_format='legacy_v1',
    message_type='abb',
    has_device=False,
))

# --- That Place v1: command acknowledgement ---
# Topic: that-place/scout/{scout_serial}/{device_serial}/cmd/ack
# Registered after telemetry patterns; more specific than the wildcard subscription.
router.register(TopicPattern(
    name='that_place_v1_cmd_ack',
    regex=re.compile(r'^that-place/scout/(?P<scout>[^/]+)/(?P<device>[^/]+)/cmd/ack$'),
    topic_format='that_place_v1',
    message_type='cmd_ack',
    has_device=True,
))

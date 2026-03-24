"""Tests for Sprint 6: MQTT topic router.

All tests are pure unit tests — no MQTT broker or database required.
The router is a stateless pattern-matching module that returns ParsedTopic
objects from topic strings.

Ref: SPEC.md § Feature: MQTT Topic Router
"""
import pytest

from apps.ingestion.router import router

# ---------------------------------------------------------------------------
# Legacy v1 — fm/mm/{unit_serial}/{message_type}
# ---------------------------------------------------------------------------


class TestLegacyV1Telemetry:

    def test_matches_telemetry_topic(self):
        result = router.route('fm/mm/UNIT123/telemetry')
        assert result is not None
        assert result.pattern_name == 'legacy_v1_telemetry'

    def test_extracts_device_serial(self):
        result = router.route('fm/mm/SCOUT-ABC-001/telemetry')
        assert result.device_serial == 'SCOUT-ABC-001'

    def test_scout_serial_equals_device_serial_in_v1(self):
        result = router.route('fm/mm/UNIT999/telemetry')
        assert result.scout_serial == result.device_serial == 'UNIT999'

    def test_topic_format_is_legacy_v1(self):
        result = router.route('fm/mm/UNIT123/telemetry')
        assert result.topic_format == 'legacy_v1'

    def test_message_type_is_telemetry(self):
        result = router.route('fm/mm/UNIT123/telemetry')
        assert result.message_type == 'telemetry'

    def test_leading_slash_is_stripped(self):
        """Legacy units sometimes publish with a leading slash — must still match."""
        result = router.route('/fm/mm/UNIT123/telemetry')
        assert result is not None
        assert result.device_serial == 'UNIT123'


class TestLegacyV1Weatherstation:

    def test_matches_weatherstation_topic(self):
        result = router.route('fm/mm/WS001/weatherstation')
        assert result is not None
        assert result.pattern_name == 'legacy_v1_weatherstation'

    def test_extracts_serial(self):
        result = router.route('fm/mm/WS-NORTH/weatherstation')
        assert result.device_serial == 'WS-NORTH'

    def test_message_type(self):
        result = router.route('fm/mm/WS001/weatherstation')
        assert result.message_type == 'weatherstation'

    def test_topic_format(self):
        result = router.route('fm/mm/WS001/weatherstation')
        assert result.topic_format == 'legacy_v1'

    def test_leading_slash_variant(self):
        result = router.route('/fm/mm/WS001/weatherstation')
        assert result is not None
        assert result.device_serial == 'WS001'


class TestLegacyV1TBox:

    def test_matches_tbox_topic(self):
        result = router.route('fm/mm/TBOX001/tbox')
        assert result is not None
        assert result.pattern_name == 'legacy_v1_tbox'

    def test_extracts_serial(self):
        result = router.route('fm/mm/TB-ZONE-3/tbox')
        assert result.device_serial == 'TB-ZONE-3'

    def test_message_type(self):
        result = router.route('fm/mm/TBOX001/tbox')
        assert result.message_type == 'tbox'

    def test_leading_slash_variant(self):
        result = router.route('/fm/mm/TBOX001/tbox')
        assert result is not None


class TestLegacyV1ABB:

    def test_matches_abb_topic(self):
        result = router.route('fm/mm/ABB001/abb')
        assert result is not None
        assert result.pattern_name == 'legacy_v1_abb'

    def test_extracts_serial(self):
        result = router.route('fm/mm/ABB-DRIVE-7/abb')
        assert result.device_serial == 'ABB-DRIVE-7'

    def test_message_type(self):
        result = router.route('fm/mm/ABB001/abb')
        assert result.message_type == 'abb'

    def test_leading_slash_variant(self):
        result = router.route('/fm/mm/ABB001/abb')
        assert result is not None


# ---------------------------------------------------------------------------
# That Place v1 — Scout own telemetry
# that-place/scout/{scout_serial}/telemetry
# ---------------------------------------------------------------------------

class TestThatPlaceV1ScoutTelemetry:

    def test_matches_scout_telemetry_topic(self):
        result = router.route('that-place/scout/SCOUT-001/telemetry')
        assert result is not None
        assert result.pattern_name == 'that_place_v1_scout_telemetry'

    def test_extracts_scout_serial(self):
        result = router.route('that-place/scout/FM-SCOUT-42/telemetry')
        assert result.scout_serial == 'FM-SCOUT-42'

    def test_scout_serial_equals_device_serial(self):
        """Scout own telemetry — the Scout IS the device being looked up."""
        result = router.route('that-place/scout/SCOUT-001/telemetry')
        assert result.scout_serial == result.device_serial

    def test_topic_format_is_that_place_v1(self):
        result = router.route('that-place/scout/SCOUT-001/telemetry')
        assert result.topic_format == 'that_place_v1'

    def test_message_type_is_scout_telemetry(self):
        result = router.route('that-place/scout/SCOUT-001/telemetry')
        assert result.message_type == 'scout_telemetry'


# ---------------------------------------------------------------------------
# That Place v1 — device telemetry bridged through Scout
# that-place/scout/{scout_serial}/{device_serial}/telemetry
# ---------------------------------------------------------------------------

class TestThatPlaceV1DeviceTelemetry:

    def test_matches_device_telemetry_topic(self):
        result = router.route('that-place/scout/SCOUT-001/SENSOR-007/telemetry')
        assert result is not None
        assert result.pattern_name == 'that_place_v1_device_telemetry'

    def test_extracts_both_serials(self):
        result = router.route('that-place/scout/SCOUT-001/SENSOR-007/telemetry')
        assert result.scout_serial == 'SCOUT-001'
        assert result.device_serial == 'SENSOR-007'

    def test_scout_and_device_serials_are_different(self):
        result = router.route('that-place/scout/GW-100/DEV-200/telemetry')
        assert result.scout_serial != result.device_serial

    def test_topic_format_is_that_place_v1(self):
        result = router.route('that-place/scout/SCOUT-001/SENSOR-007/telemetry')
        assert result.topic_format == 'that_place_v1'

    def test_message_type_is_telemetry(self):
        result = router.route('that-place/scout/SCOUT-001/SENSOR-007/telemetry')
        assert result.message_type == 'telemetry'

    def test_does_not_match_scout_only_topic(self):
        """3-segment v1 topic must not match the 4-segment device pattern."""
        result = router.route('that-place/scout/SCOUT-001/telemetry')
        assert result.pattern_name == 'that_place_v1_scout_telemetry'
        assert result.device_serial == 'SCOUT-001'


# ---------------------------------------------------------------------------
# Outbound / unknown topics — must return None
# ---------------------------------------------------------------------------

class TestUnknownAndOutboundTopics:

    def test_legacy_relays_not_matched(self):
        """Outbound relay command topic — we do not process inbound relays."""
        assert router.route('fm/mm/UNIT123/relays') is None

    def test_legacy_admin_not_matched(self):
        """Outbound admin command topic — we do not subscribe to these."""
        assert router.route('fm/mm/UNIT123/admin') is None

    def test_completely_unknown_topic_returns_none(self):
        assert router.route('some/random/topic') is None

    def test_empty_topic_returns_none(self):
        assert router.route('') is None

    def test_partial_legacy_topic_returns_none(self):
        assert router.route('fm/mm/UNIT123') is None

    def test_partial_v2_topic_returns_none(self):
        assert router.route('that-place/scout/SCOUT-001') is None

    def test_unknown_message_type_not_matched(self):
        assert router.route('fm/mm/UNIT123/unknowntype') is None


# ---------------------------------------------------------------------------
# Topic format detection
# ---------------------------------------------------------------------------

class TestTopicFormatDetection:

    def test_all_legacy_v1_patterns_report_legacy_format(self):
        topics = [
            'fm/mm/U/telemetry',
            'fm/mm/U/weatherstation',
            'fm/mm/U/tbox',
            'fm/mm/U/abb',
        ]
        for topic in topics:
            result = router.route(topic)
            assert result is not None, f'Expected match for {topic}'
            assert result.topic_format == 'legacy_v1', f'Wrong format for {topic}'

    def test_all_v1_patterns_report_that_place_v1_format(self):
        topics = [
            'that-place/scout/S1/telemetry',
            'that-place/scout/S1/D1/telemetry',
        ]
        for topic in topics:
            result = router.route(topic)
            assert result is not None, f'Expected match for {topic}'
            assert result.topic_format == 'that_place_v1', f'Wrong format for {topic}'

    def test_parsed_topic_is_frozen(self):
        """ParsedTopic must be immutable — prevents accidental mutation."""
        result = router.route('fm/mm/UNIT/telemetry')
        with pytest.raises((AttributeError, TypeError)):
            result.device_serial = 'HACKED'

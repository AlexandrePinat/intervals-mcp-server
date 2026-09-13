"""
Unit tests for the Value and Step dataclasses in intervals_mcp_server.utils.types.

These tests verify that the Value dataclass correctly handles:
- String formatting for percent FTP units
- Ramp intervals (start/end values)
- Deserialisation of pace/swim-pace unit strings returned by the Intervals.icu API
and that a Step renders its text as the cue before the duration.
"""

import pytest

from intervals_mcp_server.utils.types import Value, ValueUnits, WorkoutDoc


def test_str_percent_ftp():
    """Test formatting percentage FTP values."""
    val = Value(value=95.0, units=ValueUnits.PERCENT_FTP)
    assert str(val) == "95% ftp"


def test_str_ramp_percent_ftp():
    """Test formatting ramp intervals with percentage FTP."""
    val = Value(start=65, end=85, units=ValueUnits.PERCENT_FTP)
    assert str(val) == "65%-85% ftp"


@pytest.mark.parametrize(
    "unit_str,expected_enum",
    [
        ("MINS_KM", ValueUnits.MINS_KM),
        ("MINS_MILE", ValueUnits.MINS_MILE),
        ("SECS_100M", ValueUnits.SECS_100M),
        ("SECS_500M", ValueUnits.SECS_500M),
    ],
)
def test_pace_units_deserialise_from_api_string(unit_str, expected_enum):
    """Pace/swim-pace unit strings returned by the Intervals.icu API must round-trip
    through Value.from_dict without raising ValueError.  This test would fail if any
    of these unit strings were missing from the ValueUnits enum."""
    val = Value.from_dict({"value": 5.0, "units": unit_str})
    assert val.units == expected_enum


def test_step_text_is_the_cue_before_the_duration():
    """Intervals.icu takes the text before the first duration as the step cue shown on the
    watch (upstream issue #132): the label leads the line instead of trailing the targets."""
    doc = WorkoutDoc.from_dict(
        {
            "steps": [
                {
                    "reps": 10,
                    "text": "Main",
                    "steps": [
                        {
                            "text": "Sprint",
                            "distance": 40,
                            "hr": {"value": 5, "units": "hr_zone"},
                            "intensity": "active",
                        },
                        {"text": "Rest", "duration": 30, "intensity": "rest"},
                    ],
                },
                {"text": "Stretch"},
            ]
        }
    )
    lines = [line.strip() for line in str(doc).splitlines()]
    assert "10x Main" in lines
    assert "- Sprint 40mtr intensity=active Z5 HR" in lines
    assert "- Rest 30s intensity=rest" in lines
    assert "Stretch" in lines

import unittest

from jablotron100 import AlarmState, SectionPrimaryState
from jablotron100.state import parse_pg_output_states, parse_section_states


class StateParserTests(unittest.TestCase):
    def test_disarmed_section_and_unused_section_marker(self) -> None:
        states = parse_section_states(bytes.fromhex("510401000700"))

        self.assertEqual(list(states), [1])
        self.assertEqual(states[1].primary, SectionPrimaryState.DISARMED)
        self.assertEqual(states[1].alarm_state, AlarmState.DISARMED)
        self.assertFalse(states[1].problem)

    def test_section_alarm_flags_have_priority(self) -> None:
        # Bit 3 indicates a triggered section; primary state remains disarmed.
        states = parse_section_states(bytes.fromhex("510411000700"))

        self.assertTrue(states[1].triggered)
        self.assertEqual(states[1].alarm_state, AlarmState.TRIGGERED)

    def test_pg_outputs_are_little_endian_bit_fields(self) -> None:
        states = parse_pg_output_states(bytes.fromhex("50020580"), 16)

        self.assertTrue(states[1])
        self.assertFalse(states[2])
        self.assertTrue(states[3])
        self.assertTrue(states[16])

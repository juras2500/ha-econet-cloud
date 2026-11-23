"""Regression checks against wire-shaped data, using only the standard library."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "custom_components" / "econet_cloud"))
from model import Reading, parameter_updates, profile_readings
from protocol import mqtt_packet, mqtt_packets


class ReadingTests(unittest.TestCase):
    def test_wire_values_and_component_isolation(self):
        message = {"messages": [{"name": "GET_VALUES", "targets": [
            {"component": "vent", "parameters": {"6204": {"0": 136}, "@humidity": {"value": [30]}, "bad": {"status": 1}}},
            {"component": "panel", "parameters": {"6204": [221]}},
            {"component": "offline", "statusCode": 4, "parameters": {"6204": {"0": 999}}},
        ]}]}
        values = parameter_updates(message)
        self.assertEqual(values, {("vent", "u6204"): 136, ("vent", "humidity"): 30, ("panel", "u6204"): 221})
        self.assertEqual(Reading("vent", "u6204", "Temp.", "°C", -1, 1).value(values["vent", "u6204"]), 13.6)

    def test_partial_cloud_response_retains_valid_stable_readings(self):
        # Actual response shape: one unsupported optional parameter makes the
        # target partial, while values such as speed and filters remain valid.
        payload = {"transactionId": "3", "operations": [{"name": "GET_VALUES", "statusCode": 0,
            "targets": [{"component": "vent", "statusCode": 1, "parameters": {
                "65535": ["unsupported optional parameter"],
                "u81": [1, 0, 4], "u6322": [0, 0, 1], "u7151": [3, 0, 99],
                "u7076": [28, 0, 180], "u6205": [17.2, -50, 100],
            }}]}]}
        self.assertEqual(parameter_updates(payload), {
            ("vent", "u81"): 1, ("vent", "u6322"): 0, ("vent", "u7151"): 3,
            ("vent", "u7076"): 28, ("vent", "u6205"): 17.2,
        })

    def test_profile_uses_display_metadata_without_controls(self):
        profile = {"tiles": [{"title": "@supply", "actualValue": {"parameterName": "u1", "unit": "m3/h"}},
                              {"title": "@mode", "setValue": {"parameterName": "u2", "options": {"1": {"description": "@manual"}}}}],
                   "advancedParameters": {"access": {"password": "not-relevant"}}}
        readings = profile_readings(profile, {"supply": "Nawiew", "mode": "Tryb", "manual": "Ręczny"}, "vent")
        self.assertEqual([(r.name, r.unit) for r in readings], [("Nawiew", "m³/h"), ("Tryb", None)])
        self.assertEqual(readings[1].value(1), "Ręczny")
        self.assertIsNone(readings[1].value(9))

    def test_invalid_readings_cannot_become_energy_or_temperature_spikes(self):
        self.assertIsNone(Reading("vent", "x", "Temp.", "°C").value(65535))
        self.assertIsNone(Reading("vent", "x", "RH", "%").value(255))
        self.assertIsNone(Reading("vent", "x", "Flow", "m³/h").value(-1))

    def test_filters_and_temperature_metadata_from_actual_profile_screen(self):
        profile = {"tiles": [{"actualValue": {"title": "@room", "parameterName": "u6338"}}],
                   "editionScreens": [{"id": "edit_work_modes", "barParams": [
                       {"title": "@room", "parameterName": "u6338", "unit": "°C", "precision": 1},
                       {"title": "@filters", "parameterName": "u7076", "unit": "d"},
                       {"title": "@filters", "parameterName": "u7076", "unit": "d"},
                       {"title": "@supply_filter", "parameterName": "u6938", "unit": "%"},
                       {"title": "@exhaust_filter", "parameterName": "u6939", "unit": "%"}]}]}
        readings = profile_readings(profile, {"room": "Temp. pomieszczenia", "filters": "Wymiana filtrów",
                                             "supply_filter": "Zużycie filtr nawiew", "exhaust_filter": "Zużycie filtr wywiew"}, "vent")
        by_key = {reading.key[1]: reading for reading in readings}
        self.assertEqual(len(readings), 4)
        self.assertEqual(by_key["u6338"].unit, "°C")
        self.assertEqual(by_key["u6338"].value(22.6863), 22.7)
        self.assertEqual(by_key["u7076"].unit, "d")
        self.assertEqual(by_key["u6938"].value(84), 84)

    def test_fragmented_and_coalesced_mqtt_frames(self):
        first = mqtt_packet(0x30, b"x" * 200)
        buffer = bytearray(first[:3])
        self.assertEqual(mqtt_packets(buffer), [])
        buffer.extend(first[3:] + b"\xd0\x00")
        self.assertEqual(mqtt_packets(buffer), [(3, 0, b"x" * 200), (13, 0, b"")])
        self.assertEqual(buffer, bytearray())

    def test_malformed_frame_is_rejected(self):
        with self.assertRaises(ValueError):
            mqtt_packets(bytearray(b"\x30\xff\xff\xff\xff"))


if __name__ == "__main__":
    unittest.main()

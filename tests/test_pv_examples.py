"""Evaluate the actual published PV templates against independent scenarios."""

from datetime import datetime, timedelta, timezone
import json
import pathlib
import unittest

from jinja2 import Environment
import yaml

ROOT = pathlib.Path(__file__).parents[1]
NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


class Reading:
    def __init__(self, value, attributes=None, age=20):
        self.state = str(value)
        self.attributes = attributes or {}
        self.last_reported = NOW - timedelta(seconds=age)


class States(dict):
    def __getitem__(self, key):
        return self.get(key)

    def __call__(self, key):
        return self[key].state if self[key] else "unknown"


def timestamp(value, default=None):
    if isinstance(value, (int, float)):
        return value
    try:
        return (value if isinstance(value, datetime) else datetime.fromisoformat(value)).timestamp()
    except (TypeError, ValueError):
        return default


def from_json(value, default=None):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False, "on": True, "off": False}.get(str(value).strip().lower(), default)


class PvExampleTests(unittest.TestCase):
    def setUp(self):
        self.states = States({
            "input_boolean.example_pv_dhw_enabled": Reading("on"),
            "input_boolean.example_pv_co_enabled": Reading("on"),
            "input_text.example_pv_co_session": Reading("{}"),
            "sun.sun": Reading("above_horizon", {"next_setting": (NOW + timedelta(hours=3)).isoformat()}),
            "sensor.grid_power": Reading(-3000), "sensor.pv_power": Reading(4000),
            "sensor.pv_forecast_next_hour": Reading(2.2),
            "binary_sensor.heat_pump_alarm": Reading("off"),
            "binary_sensor.heat_pump_live": Reading("on"),
            "water_heater.heat_pump_dhw": Reading("on", {"temperature": 50, "current_temperature": 40}),
            "button.heat_pump_dhw_once": Reading((NOW - timedelta(days=1)).isoformat()),
            "number.heat_pump_comfort_target": Reading(22, {"min": 10, "max": 30}),
            "sensor.heating_room_temperature": Reading(21.8),
            "sensor.outdoor_temperature": Reading(5),
            "select.heat_pump_heating_mode": Reading("1"),
            "sensor.heat_pump_three_way_valve": Reading("central_heating"),
            "automation.example_pv_dhw": Reading("on", {"current": 0}),
        })
        self.env = Environment()
        self.env.filters.update(bool=as_bool, from_json=from_json, to_json=json.dumps)
        self.env.globals.update(states=self.states, now=lambda: NOW,
            today_at=lambda _: NOW.replace(hour=0, minute=0), as_timestamp=timestamp,
            is_state=lambda entity, values: self.states(entity) in values if isinstance(values, list)
                                            else self.states(entity) == values,
            state_attr=lambda entity, attr: self.states[entity].attributes.get(attr) if self.states[entity] else None)
        self.co = yaml.safe_load((ROOT / "examples/pv/co.package.yaml").read_text())["automation"][0]
        self.dhw = yaml.safe_load((ROOT / "examples/pv/dhw.package.yaml").read_text())["automation"][0]

    def co_decision(self):
        return self.env.from_string(self.co["actions"][0]["variables"]["next_action"]).render().strip()

    def dhw_eligible(self):
        return as_bool(self.env.from_string(self.dhw["conditions"][0]["value_template"]).render())

    def session(self, **changes):
        data = dict(baseline=22, bumped=22.5, until=NOW.timestamp() + 1800, day="2026-01-15")
        data.update(changes)
        self.states["input_text.example_pv_co_session"] = Reading(json.dumps(data))
        self.states["number.heat_pump_comfort_target"].state = "22.5"

    def test_stable_export_and_forecast_are_eligible(self):
        self.assertTrue(self.dhw_eligible())
        self.assertEqual(self.co_decision(), "start")

    def test_permissions_default_off_and_gate_new_starts(self):
        for name in ("dhw", "co"):
            doc = yaml.safe_load((ROOT / f"examples/pv/{name}.package.yaml").read_text())
            self.assertFalse(doc["input_boolean"][f"example_pv_{name}_enabled"]["initial"])
        self.states["input_boolean.example_pv_co_enabled"].state = "off"
        self.states["input_boolean.example_pv_dhw_enabled"].state = "off"
        self.assertEqual(self.co_decision(), "idle")
        self.assertFalse(self.dhw_eligible())

    def test_positive_grid_power_is_import(self):
        self.states["sensor.grid_power"].state = "3000"
        self.assertEqual(self.co_decision(), "idle")
        self.assertFalse(self.dhw_eligible())

    def test_stale_grid_or_missing_forecast_prevents_heating(self):
        self.states["sensor.grid_power"].last_reported = NOW - timedelta(minutes=3)
        self.assertEqual(self.co_decision(), "idle")
        self.assertFalse(self.dhw_eligible())
        self.states["sensor.grid_power"].last_reported = NOW
        self.states["sensor.pv_forecast_next_hour"].state = "unavailable"
        self.assertEqual(self.co_decision(), "idle")
        self.assertFalse(self.dhw_eligible())

    def test_once_per_day_guards(self):
        self.states["input_text.example_pv_co_session"].state = json.dumps({"day": "2026-01-15"})
        self.states["button.heat_pump_dhw_once"].state = NOW.isoformat()
        self.assertEqual(self.co_decision(), "idle")
        self.assertFalse(self.dhw_eligible())

    def test_co_warm_room_or_cap_prevents_new_boost(self):
        self.states["sensor.heating_room_temperature"].state = "23.5"
        self.assertEqual(self.co_decision(), "idle")
        self.states["sensor.heating_room_temperature"].state = "20"
        self.states["number.heat_pump_comfort_target"].state = "23.2"
        self.assertEqual(self.co_decision(), "idle")

    def test_import_or_timeout_restores_active_session(self):
        self.session()
        self.states["sensor.grid_power"].state = "600"
        self.assertEqual(self.co_decision(), "restore")
        self.states["sensor.grid_power"].state = "-3000"
        self.session(until=NOW.timestamp() - 1)
        self.assertEqual(self.co_decision(), "restore")

    def test_manual_change_is_preserved(self):
        self.session()
        self.states["number.heat_pump_comfort_target"].state = "23"
        self.assertEqual(self.co_decision(), "forget")

    def test_disable_after_restart_restores_when_controller_returns(self):
        self.session()
        self.states["input_boolean.example_pv_co_enabled"].state = "off"
        self.states["binary_sensor.heat_pump_live"].state = "off"
        self.assertEqual(self.co_decision(), "idle")
        self.states["binary_sensor.heat_pump_live"].state = "on"
        self.assertEqual(self.co_decision(), "restore")

    def test_memory_has_no_initial_reset_and_writes_follow_checkpoint(self):
        doc = yaml.safe_load((ROOT / "examples/pv/co.package.yaml").read_text())
        self.assertNotIn("initial", doc["input_text"]["example_pv_co_session"])
        sequence = self.co["actions"][1]["choose"][2]["sequence"]
        services = [step["action"] for step in sequence if "action" in step]
        self.assertEqual(services, ["input_text.set_value", "number.set_value"])
        self.assertTrue(any(step.get("trigger") == "homeassistant" for step in self.co["triggers"]))

    def test_all_published_templates_compile(self):
        def visit(node):
            if isinstance(node, dict):
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
            elif isinstance(node, str) and ("{{" in node or "{%" in node):
                self.env.parse(node)
        visit(self.co)
        visit(self.dhw)

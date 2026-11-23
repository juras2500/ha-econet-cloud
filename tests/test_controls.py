"""Controller commands, error handling and readback without a live device."""

import asyncio
import importlib
import json
import pathlib
import sys
import time
import types
import unittest
from unittest.mock import patch

root = pathlib.Path(__file__).parents[1] / "custom_components" / "econet_cloud"
package = types.ModuleType("econet_control_test_package")
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
client_module = importlib.import_module(package.__name__ + ".client")
controls = importlib.import_module(package.__name__ + ".controls")
model = importlib.import_module(package.__name__ + ".model")
protocol = importlib.import_module(package.__name__ + ".protocol")


class ControlModelTests(unittest.TestCase):
    def test_reviewed_profile_interface_and_unknown_profile_gate(self):
        fixture = json.loads((pathlib.Path(__file__).parent / "fixtures/vent-controls-profile.json").read_text())
        self.assertEqual(controls.ControlProfile.discover(fixture, "vent").component, "vent")
        self.assertIsNone(controls.ControlProfile.discover({}, "vent"))
        fixture["editionScreens"][0]["tiles"] = [t for t in fixture["editionScreens"][0]["tiles"]
                                                if t["quickEdition"]["editParam"]["parameterName"] != "u6630"]
        self.assertIsNone(controls.ControlProfile.discover(fixture, "vent"))

    def test_speed_boost_masks_and_external_source_guard(self):
        state = {"u81": 3, "u6630": 0, "u6639": 512, "u7074": 1}
        self.assertEqual(controls.speed_command("speed_2", state), {"u81": "4"})
        self.assertEqual(controls.speed_command("pause", state), {"u81": "6"})
        self.assertEqual(controls.speed_command("boost_1", state), {"u6639": "H64L384"})
        self.assertEqual(controls.speed_command("boost_2", state), {"u6639": "H128L320"})
        state["u6639"] |= 64
        self.assertEqual(controls.current_speed(state), "boost_1")
        self.assertEqual(controls.speed_command("speed_1", state), {"u81": "3", "u6639": "H0L192"})
        self.assertTrue(controls.command_matches({"u6639": "H0L192"}, {"u6639": 512}))
        state["u6639"] |= 1
        with self.assertRaises(controls.ControlError):
            controls.speed_command("speed_2", state)

    def test_manual_speed_does_not_silently_replace_a_schedule(self):
        state = {"u81": 3, "u6630": 257, "u6639": 0, "u7074": 1}
        with self.assertRaises(controls.ControlError):
            controls.speed_command("speed_2", state)
        self.assertEqual(controls.mode_command("manual", state), {"u6630": "H0L1"})
        self.assertEqual(controls.speed_command("boost_1", state), {"u6639": "H64L384"})

    def test_temperature_uses_device_limits_and_rejects_nonfinite_steps(self):
        bounds = {"u6342": (18, 30)}
        self.assertEqual(controls.temperature_command("u6342", 25, bounds), {"u6342": "25"})
        for value in [17, 31, 24.5, float("nan"), float("inf"), True]:
            with self.assertRaises(controls.ControlError):
                controls.temperature_command("u6342", value, bounds)
        with self.assertRaises(controls.ControlError):
            controls.validate_write({"u6904": "7"}, bounds)  # No filter reset exposed.
        with self.assertRaises(controls.ControlError):
            controls.validate_write({"u6639": "H65535L0"}, bounds)

    def test_write_status_codes_are_not_decoded_as_sensor_values(self):
        ack = {"operations": [{"name": "PARAMS_MODIFICATION", "statusCode": 0,
                               "targets": [{"component": "vent", "parameters": {"u81": "0", "u6342": "16"}}]}]}
        self.assertEqual(model.parameter_updates(ack), {})
        self.assertEqual(model.parameter_bounds(ack), {})

    def test_device_numeric_limits_from_partial_response(self):
        payload = {"operations": [{"name": "GET_VALUES", "targets": [{"component": "vent", "statusCode": 1,
                    "parameters": {"u6342": [24, 18, 30], "u6343": [100, 18, 30], "u6344": [24]}}]}]}
        self.assertEqual(model.parameter_bounds(payload), {("vent", "u6342"): (18, 30)})


class CommandRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = client_module.CloudClient(None, None, "test-user", "test-refresh", "test-installation")
        self.client.control_profile = controls.ControlProfile("vent")
        self.client._client_id = "test-client"
        self.client.connected = True
        self.wire = {"u81": 3, "u6630": 256, "u6639": 512, "u7074": 1,
                     "u6342": 24, "u6343": 23, "u6344": 22}
        self.client.values = {("vent", k): v for k, v in self.wire.items()}
        self.client.seen = {key: time.monotonic() for key in self.client.values}
        self.client.bounds = {key: (18, 30) for key in controls.TEMPERATURE_KEYS}
        self.log = []
        self.reject = False
        self.readback = True
        self.client._send = self.send

    async def response(self, transaction, operation):
        body = {"transactionId": transaction, "operations": [operation]}
        payload = protocol.mqtt_string("test/test-client/installationResponse") + json.dumps(body).encode()
        await self.client._published(0, payload)

    async def send(self, packet):
        _, _, payload = protocol.mqtt_packets(bytearray(packet))[0]
        length = int.from_bytes(payload[:2], "big")
        body = json.loads(payload[2 + length:])
        operation = body["operations"][0]
        parameters = operation["targets"][0]["parameters"]
        self.log.append((operation["name"], tuple(parameters)))
        if operation["name"] == "PARAMS_MODIFICATION":
            before = dict(self.client.values)
            if not self.reject:
                for key, value in parameters.items():
                    if value.startswith("H"):
                        high, low = (int(n) for n in value[1:].split("L"))
                        self.wire[key] = (self.wire[key] | high) & ~low
                    else:
                        self.wire[key] = float(value)
            await self.response(body["transactionId"], {"name": "PARAMS_MODIFICATION", "statusCode": 0,
                "targets": [{"component": "vent", "parameters": {key: "1" if self.reject else "0" for key in parameters}}]})
            self.assertEqual(self.client.values, before, "An ACK must not optimistically change readings")
        elif self.readback:
            values = {key: [self.wire[key], 18, 30] if key in controls.TEMPERATURE_KEYS else [self.wire[key]] for key in parameters}
            await self.response(body["transactionId"], {"name": "GET_VALUES", "statusCode": 0,
                "targets": [{"component": "vent", "statusCode": 0, "parameters": values}]})

    async def test_boost_switch_normal_return_and_unrelated_bits_preserved(self):
        await self.client.set_speed("boost_1")
        self.assertEqual(self.client.control_state()["u6639"], 576)
        await self.client.set_speed("boost_2")
        self.assertEqual(self.client.control_state()["u6639"], 640)
        await self.client.set_speed("speed_2")
        self.assertEqual(self.client.control_state()["u6639"], 512)
        self.assertEqual(self.client.control_state()["u81"], 4)
        self.assertEqual(self.client.confirmed_commands, 3)

    async def test_rejected_command_keeps_previous_state(self):
        self.reject = True
        with self.assertRaises(client_module.CloudError):
            await self.client.set_temperature("u6342", 25)
        self.assertEqual(self.client.control_state()["u6342"], 24)
        self.assertEqual(self.client.confirmed_commands, 0)

    async def test_stop_boost_keeps_schedule_and_base_speed(self):
        await self.client.set_mode("schedule")
        await self.client.set_speed("boost_1")
        await self.client.stop_boost()
        self.assertEqual(self.client.control_state()["u6639"], 512)
        self.assertEqual(self.client.control_state()["u6630"], 257)
        self.assertEqual(self.client.control_state()["u81"], 3)

    async def test_external_boost_cannot_be_stopped_by_overwriting_status_bits(self):
        self.client.values["vent", "u6639"] = 513
        with self.assertRaises(controls.ControlError):
            await self.client.stop_boost()
        self.assertEqual(self.log, [])

    async def test_concurrent_entity_commands_are_serialized_until_readback(self):
        await asyncio.gather(self.client.set_speed("speed_2"), self.client.set_temperature("u6342", 25))
        self.assertEqual([name for name, _ in self.log], ["PARAMS_MODIFICATION", "GET_VALUES"] * 2)
        self.assertEqual(self.client.control_state()["u6342"], 25)

    async def test_missing_readback_is_not_success(self):
        self.readback = False
        real_wait_for = asyncio.wait_for
        async def short_wait(awaitable, timeout):
            return await real_wait_for(awaitable, min(timeout, 0.02))
        with patch.object(client_module.asyncio, "wait_for", short_wait):
            with self.assertRaises(client_module.CloudError):
                await self.client.set_temperature("u6342", 25)
        self.assertEqual(self.client.control_state()["u6342"], 24)
        self.assertEqual(self.client.confirmed_commands, 0)

    async def test_unrelated_parameter_rejected_before_network(self):
        with self.assertRaises(controls.ControlError):
            await self.client.operation("PARAMS_MODIFICATION", [{"component": "vent", "parameters": {"u6904": "7"}}])
        self.assertEqual(self.log, [])

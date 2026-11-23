"""Only operational counters, never credentials or signed URLs."""


async def async_get_config_entry_diagnostics(hass, entry):
    client = entry.runtime_data.client
    return {"connected": client.connected, "fresh_readings": client.live,
            "sensors": len(client.specs), "received_values": len(client.values),
            "message_counts": dict(client.message_counts), "response_statuses": list(client.response_statuses),
            "controls": {"supported": client.control_profile is not None,
                         "values": client.control_state(), "bounds": dict(client.bounds),
                         "confirmed_commands": client.confirmed_commands,
                         "last_command_error": client.last_command_error},
            "last_error": client.last_error, "device": client.device}

# Changelog

## 0.2.1 — initial public release

- Cloud monitoring through signed HTTPS and AWS IoT MQTT over WebSocket.
- Cognito SRP sign-in, session renewal, rotated refresh tokens and restart recovery.
- Profile-based readings, Polish and English control labels, filter status.
- Pause, three speeds, two Boosts, Manual/Schedule, three comfort temperatures.
- End manual Boost while retaining the selected operating mode.
- Profile-gated parameter allowlist, device-reported limits, serialized commands,
  acknowledgment and fresh readback; no automatic write retries.
- Native dashboard example and optional PV/DHW/space-heating packages.

Live verification on SPIROFLEX ecoVENT MINI OEM H3.4.0 / S001.34 and HA
2026.11.2 covered each speed, both Boosts, both modes and all three comfort
temperatures. End Boost was tested while Schedule remained active. Previous
settings were restored after testing. Other hardware has not been verified.

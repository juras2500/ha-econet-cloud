# PV examples / Przykłady PV

These are **optional example Home Assistant packages**, adapted from the project's own running automations. They are independent of the recuperator integration. HACS does not install them. Start permission switches default to **off**; review the mapping before turning them on.

To use packages, add this to your HA configuration, then copy the selected `*.package.yaml` files into that directory. Merge with an existing `homeassistant:` section instead of creating a second one. Check configuration before restarting.

```yaml
homeassistant:
  packages: !include_dir_named packages
```

## Required entity mapping

Replace these placeholders throughout the selected package, including inside templates:

| Placeholder | Required meaning / Znaczenie |
| --- | --- |
| `sensor.grid_power` | Grid power in W: **negative = export**, positive = import |
| `sensor.pv_power` | Current total PV generation in W |
| `sensor.pv_forecast_next_hour` | Forecast energy for the **next hour**, in kWh, not today's remaining energy |
| `binary_sensor.heat_pump_alarm` | `off` means no active controller alarm |
| `water_heater.heat_pump_dhw` | DHW entity; `current_temperature` and `temperature` attributes; heating states `on` / `schedule` |
| `button.heat_pump_dhw_once` | Controller-native one-off DHW heating command |
| `number.heat_pump_comfort_target` | Room **comfort target**, not flow-water temperature; exposes min/max |
| `sensor.heating_room_temperature` | Room temperature representing the heated circuit |
| `sensor.outdoor_temperature` | Outdoor temperature, °C |
| `binary_sensor.heat_pump_live` | `on` means live controller polling is healthy |
| `select.heat_pump_heating_mode` | Raw state `1` means normal heating; adapt to your integration |
| `sensor.heat_pump_three_way_valve` | Raw state `central_heating` means the valve serves CO |
| `automation.example_pv_dhw` | Actual DHW example automation ID after installation, used to avoid overlap |

Check raw states in Developer Tools; translated labels can differ. If your inverter uses positive export, normalize it in a template sensor before using this package. The switches and session helper named `example_pv_*` are created by the packages themselves.

## DHW / CWU

`dhw.package.yaml` requests one controller-native DHW cycle when:

- Export and PV generation stay at least 2,500 W for 10 minutes.
- The next-hour forecast is at least 1.5 kWh, the sun is up and no alarm is active.
- The water is at least 5°C below the existing DHW target, with fresh readings.
- The one-off button has not been pressed today.

The example **does not raise the DHW setpoint** or control a contactor/compressor. The heat-pump controller finishes its own cycle. Its button timestamp provides the once-per-day guard. Turn on `input_boolean.example_pv_dhw_enabled` only after mapping the entities.

## Space heating / CO

`co.package.yaml` temporarily raises the room comfort setting by at most **0.5°C**, capped at **23.2°C**, once per day for at most **one hour**. The start window is 90–300 minutes before sunset and requires stable export, PV/forecast, a room that still needs heat, outdoor temperature between −25°C and 15°C, healthy controller polling and normal CO operation.

It restores the saved setting on timeout, room warm-up, import above 500 W, insufficient PV, loss of required live conditions, or turning off the enable switch. A manual setpoint change is preserved and ends the session. Restoration waits for live controller data and checks that the target still equals the temporary value. A persistent checkpoint allows recovery after HA restarts.

**Initialize the session helper once before first use:** set `input_text.example_pv_co_session` to `{}` using `input_text.set_value`. Do not give this helper an `initial:` value: its checkpoint must survive restarts. Do not clear it during an active boost. Turn on `input_boolean.example_pv_co_enabled` after mapping and initialization. Its permission returns to off after a restart, while the automation remains able to restore an existing checkpoint.

These CO defaults describe a conservative room-target boost, not a universal heating design. Adapt the season, comfort limit and operating-state checks to the actual building and hydraulic layout. Do not map the comfort number to a flow-water target. Retain the controller's own schedules and protections.

## Po polsku

To przykłady pakietów, a nie automatycznie instalowane funkcje integracji. Podmień wszystkie encje z tabeli. Moc sieci musi mieć znak **ujemny dla eksportu**, a prognoza oznaczać kWh na **następną godzinę**. Sprawdź surowe stany selektorów w Narzędziach deweloperskich.

CWU zleca jednorazowe nagrzanie według istniejącej nastawy, po 10 minutach odpowiedniej nadwyżki. CO podnosi **temperaturę komfortu pomieszczenia**, maksymalnie o 0,5°C i nie wyżej niż 23,2°C, na maksymalnie godzinę. To nie jest nastawa temperatury wody zasilającej.

Przed pierwszym użyciem CO wpisz raz `{}` do `input_text.example_pv_co_session`. Nie dodawaj `initial:` do tego pomocnika i nie kasuj aktywnego zapisu sesji. Przełączniki `input_boolean.example_pv_*_enabled` domyślnie są wyłączone. Wyłączenie zezwolenia CO kończy podbicie i uruchamia przywracanie; po restarcie HA zapis sesji pozostaje dostępny do odtworzenia nastawy.

Progi i warunki należy dopasować do budynku, pompy i instalacji hydraulicznej. Pakiety nie zastępują sterownika pompy. Przywracanie i szacunek dla ręcznej zmiany nastawy są częścią przykładu — nie usuwaj tych sekcji przy dostosowywaniu nazw encji.

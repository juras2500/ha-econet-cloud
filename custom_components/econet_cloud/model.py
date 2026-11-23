"""Read-only profile interpretation and defensive value decoding."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re


def canonical_key(key) -> str:
    key = str(key).lstrip("@")
    return "u" + key if key.isdigit() else key


def scalar(value):
    for _ in range(5):
        if isinstance(value, dict):
            if "0" in value:
                value = value["0"]
            elif "value" in value:
                value = value["value"]
            else:
                return None
        elif isinstance(value, list):
            value = value[0] if value else None
        else:
            break
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    return value if isinstance(value, str) and len(value) <= 255 else None


def parameter_updates(payload) -> dict[tuple[str, str], object]:
    """Accept target objects only; never treat an RPC status as a reading."""
    result = {}

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            if node.get("name") in ("PARAMS_MODIFICATION", "SEQUENTIAL_PARAMS_MODIFICATION"):
                # A write acknowledgment contains status codes, not readings.
                return
            component = node.get("component", node.get("componentId", node.get("factoryNumber")))
            params = node.get("parameters")
            if component is not None and isinstance(params, dict):
                # GET_VALUES status 1 can carry a partial result: valid readings
                # plus the reserved 65535 error entry for unsupported parameters.
                if node.get("statusCode", 0) not in (0, "0", 1, "1", 16, "16"):
                    return
                for key, value in params.items():
                    if key in ("values", "statuses", "65535", "u65535"):
                        continue
                    decoded = scalar(value)
                    if decoded is not None:
                        result[str(component), canonical_key(key)] = decoded
            else:
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        visit(child)

    visit(payload)
    return result


def parameter_bounds(payload):
    """The cloud's numeric deviceValue tuple is [value, minimum, maximum]."""
    result = {}
    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if node.get("name") in ("PARAMS_MODIFICATION", "SEQUENTIAL_PARAMS_MODIFICATION"):
                return
            component, params = node.get("component"), node.get("parameters")
            if component is not None and isinstance(params, dict):
                if node.get("statusCode", 0) not in (0, "0", 1, "1", 16, "16"):
                    return
                for key, value in params.items():
                    if isinstance(value, list) and len(value) == 3:
                        actual, minimum, maximum = value
                        if (all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                                for n in value) and minimum <= actual <= maximum):
                            result[str(component), canonical_key(key)] = (minimum, maximum)
            else:
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
    visit(payload)
    return result


@dataclass
class Reading:
    component: str
    request_key: str
    name: str
    unit: str | None = None
    exponent: float = 0
    precision: int | None = None
    options: dict[str, str] = field(default_factory=dict)

    @property
    def key(self):
        return self.component, canonical_key(self.request_key)

    def value(self, raw):
        if raw is None:
            return None
        if self.options:
            candidate = str(int(raw)) if isinstance(raw, (int, float)) and float(raw).is_integer() else str(raw)
            if candidate in self.options:
                return self.options[candidate]
            for mask, label in self.options.items():
                match = re.fullmatch(r"(?:H(\d+))?(?:L(\d+))?", mask.upper())
                if match and any(match.groups()):
                    try:
                        number = int(raw)
                    except (ValueError, TypeError):
                        return None
                    high, low = (int(part or 0) for part in match.groups())
                    if number & high == high and number & low == 0:
                        return label
            return None
        if isinstance(raw, str) and (self.unit or self.exponent):
            try:
                raw = float(raw)
            except ValueError:
                return None
        if isinstance(raw, (int, float)):
            number = raw * 10 ** self.exponent
            if not math.isfinite(number):
                return None
            if self.unit == "°C" and not -60 <= number <= 100:
                return None
            if self.unit == "%" and not 0 <= number <= 100:
                return None
            if self.unit == "m³/h" and not 0 <= number <= 10000:
                return None
            return round(number, self.precision) if self.precision is not None else number
        return raw


def profile_readings(profile: dict, translations: dict, component: str, prefix="") -> list[Reading]:
    """Expose values shown by the cloud profile, without creating controls."""
    found = {}

    def translate(text):
        text = str(text or "")
        return translations.get(text, translations.get(text.lstrip("@"), text.lstrip("@")))

    def add(desc, title=None):
        if not isinstance(desc, dict) or not isinstance(desc.get("parameterName"), (str, int)):
            return
        request_key = str(desc["parameterName"])
        key = canonical_key(request_key)
        name = translate(desc.get("title") or title)
        if not name or name == key:
            return
        unit = desc.get("unit")
        if unit in ("m3/h", "m³/h"):
            unit = "m³/h"
        elif unit in ("C", "°C"):
            unit = "°C"
        elif unit in ("", "-", "none"):
            unit = None
        options = {}
        for option, meta in (desc.get("options") or {}).items():
            label = meta.get("description", meta.get("title")) if isinstance(meta, dict) else meta
            if label is not None:
                options[str(option)] = translate(label)
        exponent = desc.get("exponent", 0)
        if not isinstance(exponent, (int, float)) or not -6 <= exponent <= 6:
            exponent = 0
        precision = desc.get("precision")
        if not isinstance(precision, int) or not 0 <= precision <= 6:
            precision = None
        if key in found:
            # The same value can appear in a tile and a screen's status bar.
            # Keep its existing identity/name, but fill missing display metadata.
            previous = found[key]
            if previous.unit is None and unit:
                previous.unit = unit
                previous.exponent = exponent
            if previous.precision is None and precision is not None:
                previous.precision = precision
            return
        found[key] = Reading(component, request_key, prefix + name, unit, exponent, precision, options)

    for tile in profile.get("tiles") or []:
        if not isinstance(tile, dict):
            continue
        actual = tile.get("actualValue")
        if actual:
            add(actual, tile.get("title"))
        else:
            add(tile.get("setValue"), tile.get("title"))
    for item in profile.get("barParams") or []:
        add(item)
    for item in profile.get("charts") or []:
        add(item)
    for screen in profile.get("editionScreens") or []:
        for item in screen.get("barParams") or []:
            add(item)
    if not found:
        # Some gateway profiles expose their measurements only in their menu.
        def menu(node, title=None):
            if isinstance(node, list):
                for child in node:
                    menu(child, title)
            elif isinstance(node, dict):
                title = node.get("title", title)
                if node.get("unit") in ("°C", "C", "%", "m3/h", "m³/h"):
                    add(node, title)
                for key, child in node.items():
                    if key != "access" and isinstance(child, (dict, list)):
                        menu(child, title)
        menu(profile.get("advancedParameters", {}))
    return list(found.values())[:100]

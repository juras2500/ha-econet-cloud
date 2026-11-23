"""Restricted commands described by the ecoVENT MINI OEM user profile."""

from dataclasses import dataclass
import math

READ_KEYS = ("u81", "u6630", "u6639", "u7074", "u6342", "u6343", "u6344")
TEMPERATURE_KEYS = ("u6342", "u6343", "u6344")
SPEED_VALUES = {"speed_1": 3, "speed_2": 4, "speed_3": 5, "pause": 6}
SPEED_OPTIONS = ("pause", "speed_1", "speed_2", "speed_3", "boost_1", "boost_2")
MODE_OPTIONS = ("manual", "schedule")
MASKS = {"u6630": {"H0L1", "H1L0"}, "u6639": {"H0L192", "H64L384", "H128L320"}}


class ControlError(ValueError):
    """A command is not supported by the current controller state."""


@dataclass(frozen=True)
class ControlProfile:
    component: str
    temperature_step: float = 1

    @classmethod
    def discover(cls, profile, component):
        screens = [s for s in profile.get("editionScreens", []) if s.get("id") == "edit_work_modes"]
        edits = [tile.get("quickEdition", {}).get("editParam", {})
                 for screen in screens for tile in screen.get("tiles", [])]
        def has(key, options):
            return any(d.get("parameterName") == key and options <= set(d.get("options", {})) for d in edits)
        if not (has("u81", {"3", "4", "5", "6"})
                and has("u6630", {"H1L0", "H0L1"})
                and has("u6639", {"H0L64", "H64L384"})
                and has("u6639", {"H0L128", "H128L320"})
                and all(any(d.get("parameterName") == k and d.get("format") == "deviceValue"
                            and d.get("step", 1) == 1 for d in edits) for k in TEMPERATURE_KEYS)):
            return None
        return cls(str(component))


def integer(state, key):
    value = state.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
        raise ControlError("Brak aktualnego odczytu ustawień centrali.")
    return int(value)


def current_speed(state):
    try:
        flags = integer(state, "u6639")
        if flags & (1 | 64):
            return "boost_1"
        if flags & (2 | 128):
            return "boost_2"
        if flags & (16 | 256):
            return None
        return next((option for option, value in SPEED_VALUES.items() if integer(state, "u81") == value), None)
    except ControlError:
        return None


def speed_command(option, state):
    if option not in SPEED_OPTIONS:
        raise ControlError("Nieobsługiwany bieg.")
    if not integer(state, "u7074") & 1:
        raise ControlError("Centrala jest wyłączona. Włącz ją w ecoNET Cloud.")
    flags = integer(state, "u6639")
    if flags & (1 | 2 | 16 | 256):
        raise ControlError("Aktywne jest sterowanie zewnętrzne lub tryb Kominek. Zakończ ten tryb w sterowniku.")
    if option in SPEED_VALUES and integer(state, "u6630") & 1:
        raise ControlError("Aby wybrać bieg lub Pauzę, ustaw najpierw tryb Ręczny.")
    if current_speed(state) == option:
        return {}
    if option == "boost_1":
        return {"u6639": "H64L384"}
    if option == "boost_2":
        return {"u6639": "H128L320"}
    result = {"u81": str(SPEED_VALUES[option])}
    if flags & 192:
        result["u6639"] = "H0L192"
    return result


def mode_command(option, state):
    if option not in MODE_OPTIONS:
        raise ControlError("Nieobsługiwany tryb pracy.")
    schedule = bool(integer(state, "u6630") & 1)
    if schedule == (option == "schedule"):
        return {}
    return {"u6630": "H1L0" if option == "schedule" else "H0L1"}


def stop_boost_command(state):
    flags = integer(state, "u6639")
    if flags & (1 | 2):
        raise ControlError("Boost jest aktywowany przez sygnał zewnętrzny. Wyłącz jego źródło.")
    return {"u6639": "H0L192"} if flags & 192 else {}


def temperature_command(key, value, bounds, step=1):
    if key not in TEMPERATURE_KEYS or key not in bounds:
        raise ControlError("Brak potwierdzonego zakresu temperatury ze sterownika.")
    minimum, maximum = bounds[key]
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or not minimum <= value <= maximum or not math.isclose((value - minimum) / step, round((value - minimum) / step), abs_tol=1e-6)):
        raise ControlError("Temperatura jest poza zakresem lub krokiem obsługiwanym przez sterownik.")
    return {key: format(value, ".10g")}


def validate_write(parameters, bounds):
    if not parameters:
        raise ControlError("Puste polecenie.")
    for key, value in parameters.items():
        if not isinstance(value, str):
            raise ControlError("Nieprawidłowy format polecenia.")
        if key == "u81" and value in {str(v) for v in SPEED_VALUES.values()}:
            continue
        if key in MASKS and value in MASKS[key]:
            continue
        if key in TEMPERATURE_KEYS:
            try:
                temperature_command(key, float(value), bounds)
            except ValueError:
                raise ControlError("Nieprawidłowa temperatura.") from None
            continue
        raise ControlError("Ten parametr nie jest udostępniony do sterowania.")


def command_matches(parameters, state):
    for key, wanted in parameters.items():
        try:
            actual = state[key]
            if wanted.startswith("H"):
                high, low = (int(v) for v in wanted[1:].split("L"))
                actual = int(actual)
                if actual & high != high or actual & low:
                    return False
            elif not math.isclose(float(actual), float(wanted), abs_tol=0.01):
                return False
        except (ValueError, TypeError, KeyError):
            return False
    return True

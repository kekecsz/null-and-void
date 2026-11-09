"""Specification section 11, "Configuration": the settings loader.

Every expectation is derived from docs/parameter_defaults.yaml itself; no game value is
written into these tests.
"""

import copy

import pytest
import yaml

from nv_core.paths import PARAMETER_DEFAULTS
from nv_core.settings import SettingsError, load_settings

TABLES = ("grant_track", "journal_tiers", "talent_development_track")


def _defaults() -> dict:
    return yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))


DEFAULTS = _defaults()
ALL_SETTINGS = sorted(DEFAULTS)
INTEGER_SETTINGS = sorted(k for k, v in DEFAULTS.items() if type(v) is int)
# A top-level whole-number setting to override, taken from the file (no name written here).
SOME_SETTING = INTEGER_SETTINGS[0]


def _fields_of_type(table: str, kind: type) -> list:
    """Fields of a table whose value in the first entry has exactly this type."""
    return sorted(k for k, v in DEFAULTS[table][0].items() if type(v) is kind)


TABLE_INT_FIELDS = [(table, field) for table in TABLES for field in _fields_of_type(table, int)]
JOURNAL_BOOL_FIELDS = _fields_of_type("journal_tiers", bool)


def _write(tmp_path, data: dict):
    path = tmp_path / "parameters.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _raises_naming(name: str, call):
    with pytest.raises(SettingsError) as excinfo:
        call()
    assert name in str(excinfo.value), f"error does not name {name!r}: {excinfo.value}"
    return excinfo


# --- loading the real file -------------------------------------------------------------

def test_loads_the_parameter_file():
    """11. Configuration: game settings come from docs/parameter_defaults.yaml."""
    settings = load_settings()
    assert settings.model_dump() == DEFAULTS


def test_every_top_level_setting_is_an_attribute():
    """11. Configuration: one attribute per top-level setting."""
    settings = load_settings()
    for name, value in DEFAULTS.items():
        if name in TABLES:
            continue
        assert getattr(settings, name) == value, name


def test_grant_track_entries():
    """11. Configuration: the shape of grant_track."""
    settings = load_settings()
    assert len(settings.grant_track) == len(DEFAULTS["grant_track"])
    for entry, expected in zip(settings.grant_track, DEFAULTS["grant_track"]):
        for field in ("funding", "admin", "expected_to_maintain", "expected_to_increase"):
            assert getattr(entry, field) == expected[field], field
    # The YAML marks "no higher position" with null; the loader turns it into None.
    nulls = [i for i, row in enumerate(DEFAULTS["grant_track"]) if row["expected_to_increase"] is None]
    assert nulls, "parameter file has no null expected_to_increase"
    for i in nulls:
        assert settings.grant_track[i].expected_to_increase is None


def test_journal_tier_entries():
    """11. Configuration: the shape of journal_tiers."""
    settings = load_settings()
    assert len(settings.journal_tiers) == len(DEFAULTS["journal_tiers"])
    for tier, expected in zip(settings.journal_tiers, DEFAULTS["journal_tiers"]):
        for field, value in expected.items():
            assert getattr(tier, field) == value, field


def test_explicit_path_is_read(tmp_path):
    """11. Configuration: the loader reads the YAML file it is given."""
    data = copy.deepcopy(DEFAULTS)
    name = INTEGER_SETTINGS[0]
    data[name] = DEFAULTS[name] + 7
    settings = load_settings(path=_write(tmp_path, data))
    assert getattr(settings, name) == DEFAULTS[name] + 7


# --- errors naming the setting --------------------------------------------------------

@pytest.mark.parametrize("name", ALL_SETTINGS)
def test_missing_setting_is_named(tmp_path, name):
    """11. Configuration: stops with an error naming any setting that is missing."""
    data = copy.deepcopy(DEFAULTS)
    del data[name]
    path = _write(tmp_path, data)
    _raises_naming(name, lambda: load_settings(path=path))


@pytest.mark.parametrize("name", INTEGER_SETTINGS)
@pytest.mark.parametrize("bad_value", ["not a number", 1.5, True], ids=["string", "float", "bool"])
def test_wrong_type_is_named(tmp_path, name, bad_value):
    """11. Configuration: stops with an error naming any setting that has the wrong type."""
    data = copy.deepcopy(DEFAULTS)
    data[name] = bad_value
    path = _write(tmp_path, data)
    _raises_naming(name, lambda: load_settings(path=path))


def test_whole_number_float_is_still_the_wrong_type(tmp_path):
    """11. Configuration: value types are validated (a float where the file has an integer)."""
    name = INTEGER_SETTINGS[0]
    data = copy.deepcopy(DEFAULTS)
    data[name] = float(DEFAULTS[name])
    path = _write(tmp_path, data)
    _raises_naming(name, lambda: load_settings(path=path))


def test_unknown_setting_in_file_is_named(tmp_path):
    """11. Configuration: the file is validated against a schema (no unknown settings)."""
    data = copy.deepcopy(DEFAULTS)
    data["not_a_real_setting"] = 3
    path = _write(tmp_path, data)
    _raises_naming("not_a_real_setting", lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_entry_missing_field(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated."""
    data = copy.deepcopy(DEFAULTS)
    first_field = next(iter(data[table][0]))
    del data[table][0][first_field]
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_entry_wrong_type(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated."""
    data = copy.deepcopy(DEFAULTS)
    int_field = next(k for k, v in data[table][0].items() if type(v) is int)
    data[table][0][int_field] = "lots"
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_entry_unknown_field(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated (no unknown fields)."""
    data = copy.deepcopy(DEFAULTS)
    # A misspelling of the entry's first field, added next to the real one.
    first_field = next(iter(data[table][0]))
    data[table][0][first_field + "s"] = data[table][0][first_field]
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_entry_misspelled_field(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated (misspelled field)."""
    data = copy.deepcopy(DEFAULTS)
    # The last entry's first field renamed: one field missing and one unknown.
    entry = data[table][-1]
    first_field = next(iter(entry))
    entry[first_field.upper()] = entry.pop(first_field)
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


@pytest.mark.parametrize("table, field", TABLE_INT_FIELDS)
@pytest.mark.parametrize("bad_value", ["float", "bool"])
def test_table_whole_number_field_must_be_an_integer(tmp_path, table, field, bad_value):
    """11. Configuration: whole-number settings must be written as integers (also in the tables)."""
    data = copy.deepcopy(DEFAULTS)
    value = data[table][0][field]
    data[table][0][field] = float(value) if bad_value == "float" else True
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


def test_journal_tiers_have_boolean_fields():
    """11. Configuration: the journal_tiers table has true/false fields (precondition of the next test)."""
    assert JOURNAL_BOOL_FIELDS, "no boolean field in journal_tiers"


@pytest.mark.parametrize("field", JOURNAL_BOOL_FIELDS)
@pytest.mark.parametrize("bad_value", ["yes", 1, "maybe"], ids=["string yes", "integer 1", "string maybe"])
def test_journal_tier_boolean_field_must_be_a_bool(tmp_path, field, bad_value):
    """11. Configuration: value types are validated (a non-bool in a journal tier's true/false field)."""
    data = copy.deepcopy(DEFAULTS)
    data["journal_tiers"][0][field] = bad_value
    path = _write(tmp_path, data)
    _raises_naming("journal_tiers", lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_that_is_not_a_list(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated."""
    data = copy.deepcopy(DEFAULTS)
    data[table] = 5
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


@pytest.mark.parametrize("table", TABLES)
def test_table_entry_that_is_not_a_mapping(tmp_path, table):
    """11. Configuration: the shape of grant_track and journal_tiers is validated."""
    data = copy.deepcopy(DEFAULTS)
    data[table][0] = [1, 2, 3]
    path = _write(tmp_path, data)
    _raises_naming(table, lambda: load_settings(path=path))


# --- overrides -------------------------------------------------------------------------

def test_override_replaces_a_setting():
    """11. Configuration: defaults, then the scenario's parameter_overrides."""
    name = SOME_SETTING
    settings = load_settings({name: DEFAULTS[name] + 1})
    assert getattr(settings, name) == DEFAULTS[name] + 1
    dumped = settings.model_dump()
    for other, value in DEFAULTS.items():
        if other != name:
            assert dumped[other] == value, other


def test_override_replaces_a_whole_table():
    """11. Configuration: an override replaces the top-level setting as a whole."""
    first = dict(DEFAULTS["grant_track"][0], expected_to_increase=None)
    settings = load_settings({"grant_track": [first]})
    assert len(settings.grant_track) == 1
    assert settings.grant_track[0].funding == first["funding"]
    assert settings.grant_track[0].expected_to_increase is None


def test_override_replaces_the_whole_journal_tiers_table():
    """11. Configuration: an override of journal_tiers replaces the entire table."""
    last = copy.deepcopy(DEFAULTS["journal_tiers"][-1])
    settings = load_settings({"journal_tiers": [last]})
    assert len(settings.journal_tiers) == 1
    for field, value in last.items():
        assert getattr(settings.journal_tiers[0], field) == value, field


@pytest.mark.parametrize("table", TABLES)
def test_table_override_is_not_merged_with_the_defaults(table):
    """11. Configuration: a table override replaces the table, so each entry must be complete."""
    # One entry with a field left out: with replacement (not merging) that field is missing.
    entry = copy.deepcopy(DEFAULTS[table][0])
    del entry[next(iter(entry))]
    _raises_naming(table, lambda: load_settings({table: [entry]}))


def test_empty_or_missing_overrides_change_nothing():
    """11. Configuration: without overrides the defaults stand."""
    assert load_settings({}).model_dump() == DEFAULTS
    assert load_settings(None).model_dump() == DEFAULTS


def test_unknown_override_is_named():
    """11. Configuration: an override must name an existing setting."""
    _raises_naming("no_such_setting", lambda: load_settings({"no_such_setting": 1}))


def test_override_with_wrong_type_is_named():
    """11. Configuration: overridden values are validated like the file's."""
    name = INTEGER_SETTINGS[0]
    _raises_naming(name, lambda: load_settings({name: "seven"}))


def test_overrides_do_not_change_the_defaults():
    """11. Configuration: overrides apply to one load only."""
    name = SOME_SETTING
    load_settings({name: DEFAULTS[name] + 3})
    assert getattr(load_settings(), name) == DEFAULTS[name]


def test_override_with_a_whole_number_float_is_the_wrong_type():
    """11. Configuration: whole-number settings must be written as integers, also in overrides."""
    _raises_naming(SOME_SETTING, lambda: load_settings({SOME_SETTING: float(DEFAULTS[SOME_SETTING])}))

import json
import stat

import pytest

from salome_agent_gui import config_store as cs

SEED = {"llm": {"base_url": "", "api_key": "", "model": ""},
        "salome": {"root": "/path/to/your/SALOME"}, "policy": {}}


def _seed(tmp_path):
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(SEED))
    return p


def test_ensure_user_config_seeds_once_with_private_mode(tmp_path):
    user = tmp_path / "cfg" / "salome-agent.json"
    assert cs.ensure_user_config(user, [tmp_path / "missing.json", _seed(tmp_path)]) == user
    assert json.loads(user.read_text()) == SEED
    assert stat.S_IMODE(user.stat().st_mode) == 0o600
    user.write_text(json.dumps({"kept": True}))
    cs.ensure_user_config(user, [_seed(tmp_path)])
    assert json.loads(user.read_text()) == {"kept": True}


def test_ensure_user_config_without_seed_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        cs.ensure_user_config(tmp_path / "u.json", [tmp_path / "nope.json"])


def test_key_fields_round_trip_leaves_other_keys(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_key_fields(user, {"base_url": "http://h/v1", "model": "qwen", "api_key": "k",
                              "ssl_cert_file": "~/ca.pem"})
    assert cs.read_key_fields(user) == {"base_url": "http://h/v1", "model": "qwen", "api_key": "k",
                                        "ssl_cert_file": "~/ca.pem"}
    assert json.loads(user.read_text())["salome"] == SEED["salome"]


def test_save_raw_rejects_bad_json_and_missing_keys(tmp_path):
    from salome_agent.config import ConfigError

    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    before = user.read_text()
    with pytest.raises(ValueError):
        cs.save_raw(user, "{not json")
    with pytest.raises(ConfigError):
        cs.save_raw(user, json.dumps({"llm": {"base_url": "x"}}))
    assert user.read_text() == before
    good = dict(SEED, llm={"base_url": "http://h", "model": "m"})
    cs.save_raw(user, json.dumps(good))
    assert cs.load(user)["llm"]["model"] == "m"


def test_seed_candidates_include_the_submodule_example():
    names = [str(p) for p in cs.seed_candidates()]
    assert any(n.endswith("salome-agent/config.example.json") for n in names)


def test_read_settings_defaults_when_sections_are_missing(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    assert cs.read_settings(user) == {
        "base_url": "", "model": "", "api_key": "", "ssl_cert_file": "", "on_stage_failure": "abort",
        "tool_selection": "hints", "batch": False, "verbose": 0, "theme": "system",
        "show_reasoning": False, "verify_cadence": "final", "plan_detail": "balanced",
        "exec_retries": 2, "tool_iteration_cap": 12,
        "shared_model": True, "modules": {}, "modules_json_only": {},
        "reasoning_budget": 20000, "vision_fix_retries": 2, "timeout": 120}


def test_save_settings_writes_llm_policy_and_gui(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"base_url": "http://h/v1", "model": "m", "api_key": "k",
                            "ssl_cert_file": "/etc/ca.pem", "on_stage_failure": "continue", "tool_selection": "all",
                            "batch": True, "verbose": 2, "theme": "dark",
                            "verify_cadence": "strict", "plan_detail": "fine",
                            "exec_retries": 0, "tool_iteration_cap": 30})
    assert cs.read_settings(user) == {
        "base_url": "http://h/v1", "model": "m", "api_key": "k", "ssl_cert_file": "/etc/ca.pem",
        "on_stage_failure": "continue", "tool_selection": "all", "batch": True, "verbose": 2, "theme": "dark",
        "show_reasoning": False, "verify_cadence": "strict", "plan_detail": "fine",
        "exec_retries": 0, "tool_iteration_cap": 30,
        "shared_model": True, "modules": {}, "modules_json_only": {},
        "reasoning_budget": 20000, "vision_fix_retries": 2, "timeout": 120}
    data = json.loads(user.read_text())
    assert data["salome"] == SEED["salome"]
    assert data["gui"] == {"theme": "dark", "batch": True, "verbose": 2}


def test_save_settings_without_run_options_keeps_them(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"on_stage_failure": "continue", "batch": True, "verbose": 1})
    cs.save_settings(user, {"model": "m2", "theme": "light", "on_stage_failure": "abort",
                            "tool_selection": "all", "batch": False, "verbose": 0},
                     run_options=False)
    s = cs.read_settings(user)
    assert s["model"] == "m2" and s["theme"] == "light"
    assert (s["on_stage_failure"], s["tool_selection"], s["batch"], s["verbose"]) == \
        ("continue", "hints", True, 1)


def test_save_settings_ignores_bad_values(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"theme": "purple", "on_stage_failure": "explode",
                            "tool_selection": "some", "verbose": 9})
    s = cs.read_settings(user)
    assert (s["theme"], s["on_stage_failure"], s["tool_selection"], s["verbose"]) == \
        ("system", "abort", "hints", 2)


def test_gui_section_is_accepted_by_the_agent_config_loader(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"base_url": "http://h", "model": "m", "theme": "dark"})
    assert cs.load(user)["llm"]["model"] == "m"


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"llm": null, "gui": 3}',
                                  '{"gui": {"verbose": "lots"}}'])
def test_read_settings_falls_back_to_defaults_on_a_broken_file(tmp_path, text):
    path = tmp_path / "u.json"
    path.write_text(text)
    s = cs.read_settings(path)
    assert (s["model"], s["verbose"], s["theme"]) == ("", 0, "system")


def test_read_settings_of_a_missing_file_gives_defaults(tmp_path):
    assert cs.read_settings(tmp_path / "gone.json")["on_stage_failure"] == "abort"


def test_show_reasoning_is_saved_even_while_run_options_are_locked(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"show_reasoning": True}, run_options=False)
    assert cs.read_settings(user)["show_reasoning"] is True
    cs.save_settings(user, {"show_reasoning": False})
    assert cs.read_settings(user)["show_reasoning"] is False


def test_policy_knobs_fall_back_or_clamp_and_stay_locked(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"verify_cadence": "always", "plan_detail": "huge",
                            "exec_retries": 99, "tool_iteration_cap": 0})
    s = cs.read_settings(user)
    assert (s["verify_cadence"], s["plan_detail"], s["exec_retries"], s["tool_iteration_cap"]) \
        == ("final", "balanced", 10, 1)
    cs.save_settings(user, {"exec_retries": "x", "tool_iteration_cap": None})
    s = cs.read_settings(user)
    assert (s["exec_retries"], s["tool_iteration_cap"]) == (10, 1)   # bad input ignored
    cs.save_settings(user, {"verify_cadence": "none", "plan_detail": "coarse",
                            "exec_retries": 5, "tool_iteration_cap": 20}, run_options=False)
    s = cs.read_settings(user)
    assert (s["verify_cadence"], s["plan_detail"], s["exec_retries"], s["tool_iteration_cap"]) \
        == ("final", "balanced", 10, 1)


def test_policy_knobs_read_hand_edited_values(tmp_path):
    user = tmp_path / "u.json"
    user.write_text(json.dumps({"policy": {"exec_retries": 3, "tool_iteration_cap": 500,
                                           "verify_cadence": "none", "plan_detail": 7}}))
    s = cs.read_settings(user)
    assert (s["verify_cadence"], s["plan_detail"], s["exec_retries"], s["tool_iteration_cap"]) \
        == ("none", "balanced", 3, 60)


from salome_agent.config import LLM_KNOWN_KEYS, MODULE_LLM_KEYS


def _cfg(tmp_path, llm=None, gui=None):
    p = tmp_path / "c.json"
    data = {"llm": {"base_url": "http://h/v1", "model": "shared", "api_key": "k", **(llm or {})},
            "policy": {}}
    if gui is not None:
        data["gui"] = gui
    p.write_text(json.dumps(data))
    return p


def _row(**kw):
    return {"model": "", "base_url": "", "api_key": "", "ssl_cert_file": "", **kw}


def test_no_modules_reads_as_shared_with_advanced_defaults(tmp_path):
    s = cs.read_settings(_cfg(tmp_path))
    assert s["shared_model"] is True and s["modules"] == {} and s["modules_json_only"] == {}
    assert (s["reasoning_budget"], s["vision_fix_retries"], s["timeout"]) == (20000, 2, 120)


def test_rows_read_from_llm_modules_with_hidden_keys_listed(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "reader", "temperature": 0.2,
                                                   "extra_body": {"x": 1}}}})
    s = cs.read_settings(p)
    assert s["shared_model"] is False
    assert s["modules"] == {"vision": _row(model="reader")}
    assert s["modules_json_only"] == {"vision": ["extra_body", "temperature"]}


def test_read_settings_ignores_junk_modules(tmp_path):
    assert cs.read_settings(_cfg(tmp_path, llm={"modules": "vision"}))["modules"] == {}
    s = cs.read_settings(_cfg(tmp_path, llm={"modules": {"vision": "reader", "geom": {"model": "g"}}}))
    assert s["modules"] == {"geom": _row(model="g")}


def test_row_save_writes_only_non_empty_fields_and_keeps_hidden_keys(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "old", "temperature": 0.2}}})
    cs.save_settings(p, {"shared_model": False,
                         "modules": {"vision": _row(model=" reader "), "geom": _row()}})
    assert json.loads(p.read_text())["llm"]["modules"] == {
        "vision": {"model": "reader", "temperature": 0.2}}


def test_clearing_a_row_keeps_hidden_keys_and_drops_an_emptied_entry(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "r", "temperature": 0.2},
                                        "geom": {"model": "g"}}})
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(), "geom": _row()}})
    assert json.loads(p.read_text())["llm"]["modules"] == {"vision": {"temperature": 0.2}}
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row()}})
    cs.save_settings(p, {"shared_model": False, "modules": {}})
    assert "modules" in json.loads(p.read_text())["llm"]          # temperature still there


def test_unknown_module_entry_survives_a_save(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"visio": {"model": "typo"}}})
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(model="r")}})
    assert json.loads(p.read_text())["llm"]["modules"] == {
        "visio": {"model": "typo"}, "vision": {"model": "r"}}


def test_shared_parks_the_modules_and_unshared_brings_them_back(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "r", "extra_body": {"x": 1}}}})
    cs.save_settings(p, {"shared_model": True, "modules": {"vision": _row(model="r")}})
    data = json.loads(p.read_text())
    assert "modules" not in data["llm"]
    assert data["gui"]["parked_modules"] == {"vision": {"model": "r", "extra_body": {"x": 1}}}
    s = cs.read_settings(p)
    assert s["shared_model"] is True and s["modules"] == {"vision": _row(model="r")}
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(model="r")}})
    data = json.loads(p.read_text())
    assert data["llm"]["modules"] == {"vision": {"model": "r", "extra_body": {"x": 1}}}
    assert "parked_modules" not in data["gui"]


def test_park_merges_and_active_wins(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "new"}}},
             gui={"parked_modules": {"vision": {"model": "old", "temperature": 0.1}}})
    cs.save_settings(p, {"shared_model": True, "modules": {"vision": _row(model="new")}})
    assert json.loads(p.read_text())["gui"]["parked_modules"] == {
        "vision": {"model": "new", "temperature": 0.1}}


def test_other_endpoint_without_key_is_refused_and_nothing_written(tmp_path):
    p = _cfg(tmp_path)
    before = p.read_text()
    with pytest.raises(ValueError, match="vision: a different endpoint needs its own API key"):
        cs.save_settings(p, {"shared_model": False,
                             "modules": {"vision": _row(model="r", base_url="http://other/v1")}})
    assert p.read_text() == before


def test_same_host_row_needs_no_key(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"shared_model": False,
                         "modules": {"vision": _row(model="r", base_url="http://h/v1/")}})
    assert json.loads(p.read_text())["llm"]["modules"]["vision"]["base_url"] == "http://h/v1/"


def test_parked_rows_are_not_checked_for_keys(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"shared_model": True,
                         "modules": {"vision": _row(base_url="http://other/v1")}})
    assert json.loads(p.read_text())["gui"]["parked_modules"]["vision"] == {
        "base_url": "http://other/v1"}


def test_advanced_knobs_clamp_and_lock_with_run_options(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"reasoning_budget": 999999, "vision_fix_retries": -3, "timeout": 5})
    llm = json.loads(p.read_text())["llm"]
    assert (llm["reasoning_budget"], llm["vision_fix_retries"], llm["timeout"]) == (200000, 0, 10)
    cs.save_settings(p, {"reasoning_budget": 0, "shared_model": False,
                         "modules": {"vision": _row(model="r")}}, run_options=False)
    data = json.loads(p.read_text())
    assert data["llm"]["reasoning_budget"] == 200000 and "modules" not in data["llm"]


def test_model_label_names_one_override_and_counts_several():
    base = {"model": "shared", "shared_model": False}
    assert cs.model_label({"model": "shared", "shared_model": True,
                           "modules": {"vision": _row(model="r")}}) == ("shared", "")
    assert cs.model_label(dict(base, modules={"vision": _row(model="r")})) == (
        "shared · vision: r", "vision: r")
    assert cs.model_label(dict(base, modules={"vision": _row(base_url="http://o")})) == (
        "shared · vision: shared", "vision: shared")
    label, tip = cs.model_label(dict(base, modules={"vision": _row(model="r"),
                                                    "geom": _row(model="g"), "smesh": _row()}))
    assert label == "shared · +2 overrides" and tip == "vision: r\ngeom: g"
    assert cs.model_label({"model": "", "shared_model": True}) == ("?", "")


def test_every_engine_llm_key_is_in_the_form_or_json_only():
    form = set(cs.KEY_FIELDS) | set(cs.LLM_INTS) | {"modules"}
    missing = sorted(LLM_KNOWN_KEYS - form - cs.JSON_ONLY)
    assert not missing, f"engine llm keys with no place in the drawer: {missing}"
    missing = sorted(MODULE_LLM_KEYS - set(cs.ROW_KEYS) - cs.MODULE_JSON_ONLY)
    assert not missing, f"engine llm.modules keys with no place in the drawer: {missing}"

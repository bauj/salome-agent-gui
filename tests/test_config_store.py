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
    cs.save_key_fields(user, {"base_url": "http://h/v1", "model": "qwen", "api_key": "k"})
    assert cs.read_key_fields(user) == {"base_url": "http://h/v1", "model": "qwen", "api_key": "k"}
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

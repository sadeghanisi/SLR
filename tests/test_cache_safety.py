import json
import pickle

from housing_enhanced import SystematicReviewAutomation, _parse_json_response


class DummyAutomation:
    cache_enabled = True

    def __init__(self, cache_folder):
        self.cache_folder = cache_folder


def test_cache_load_reads_json_cache(tmp_path):
    (tmp_path / "screening_abc.json").write_text(
        json.dumps({"decision": "Likely Include"}),
        encoding="utf-8",
    )
    dummy = DummyAutomation(tmp_path)

    result = SystematicReviewAutomation._cache_load(dummy, "abc", "screening")

    assert result == {"decision": "Likely Include"}


def test_cache_load_does_not_call_pickle_load(tmp_path, monkeypatch):
    (tmp_path / "screening_abc.pkl").write_bytes(b"not trusted")
    dummy = DummyAutomation(tmp_path)

    def fail_pickle_load(*args, **kwargs):
        raise AssertionError("pickle.load must not be called during runtime cache loading")

    monkeypatch.setattr(pickle, "load", fail_pickle_load)

    result = SystematicReviewAutomation._cache_load(dummy, "abc", "screening")

    assert result is None


def test_malformed_llm_json_fallback_does_not_store_raw_response():
    raw = "Title: secret full paper text\nAPI prompt: include confidential details"

    result = _parse_json_response(raw)

    assert result["reasoning"] == "Could not parse LLM response as JSON."
    assert "secret full paper text" not in json.dumps(result)
    assert "confidential details" not in json.dumps(result)
    assert result["notes"] == "Malformed LLM response; raw response content was not stored."

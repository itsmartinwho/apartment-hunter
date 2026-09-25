"""Both model stages are mocked: preference edits never search, save or spend API credits."""

import copy
import json

import pytest

from apartment_hunter import preferences, server
from apartment_hunter.criteria import DEFAULT_LIMITS, DEFAULT_WEIGHTS
from apartment_hunter.pipeline import Hunter
from apartment_hunter.store import Store

TEXT = 'Under $6500, Chelsea only, light matters most; subway does not matter. Make Chelsea tier 1.'
PLAN = {
    "limits": {"price_max": 6500, "areas": [115]}, "tiers": {"115": 1},
    "priorities": ["light", "subway"],
    "evidence": {"limits.price_max": "Under $6500", "limits.areas": "Chelsea only",
                 "tiers.115": "Make Chelsea tier 1", "weights.light": "light matters most",
                 "weights.subway": "subway does not matter"}, "unresolved": [],
}


@pytest.fixture
def models(monkeypatch):
    cfg = {"text_key": "test-text", "typesafe_key": "test-judge", "text_model": "small-model",
           "text_base": "https://model.invalid/v1", "text_reasoning": "none", "typesafe_model": "jev-test"}
    monkeypatch.setattr(preferences, "settings", lambda: cfg)
    state = {"plan": copy.deepcopy(PLAN), "support": {}, "calls": [], "finish": "stop", "bad_answers": None}

    def fake_post(url, key, body):
        state["calls"].append((url, body))
        if url.endswith("/chat/completions"):
            return {"choices": [{"finish_reason": state["finish"],
                                 "message": {"content": json.dumps(state["plan"])}}]}
        answers = {}
        for key, question in body["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"noul": state["support"].get(key, 0.99)}
            else:
                level = 0 if key == "weights.subway" else 3
                answers[key] = {"score": level, "confidence": 0.99,
                                "probabilities": {str(i): float(i == level) for i in range(4)}}
        return {"answers": state["bad_answers"] if state["bad_answers"] is not None else answers}

    monkeypatch.setattr(preferences, "post_json", fake_post)
    return state


def interpret():
    return preferences.interpret(TEXT, DEFAULT_LIMITS, DEFAULT_WEIGHTS, {"115": 3})


def test_two_stage_preview_preserves_unmentioned_preferences(models):
    result = interpret()
    assert result["limits"]["price_max"] == 6500 and result["limits"]["areas"] == [115]
    assert result["weights"]["light"] == 10 and result["weights"]["subway"] == 0
    assert result["tiers"] == {"115": 1}
    assert result["limits"]["move_in_by"] == DEFAULT_LIMITS["move_in_by"]
    assert result["weights"]["price"] == DEFAULT_WEIGHTS["price"]
    assert len(result["changes"]) == 5 and len(models["calls"]) == 2
    text_request, judge_request = [call[1] for call in models["calls"]]
    assert text_request["reasoning"] == {"enabled": False}
    assert set(judge_request["questions"]) == set(PLAN["evidence"])
    assert "test-text" not in json.dumps(result)


def test_uncertain_limit_is_not_applied(models):
    models["support"]["limits.price_max"] = 0.4
    result = interpret()
    assert result["limits"]["price_max"] == DEFAULT_LIMITS["price_max"]
    assert result["notes"] and result["weights"]["light"] == 10


@pytest.mark.parametrize('field,value', [
    ('price_max', True), ('price_max', -1), ('price_max', 16000), ('price_max', '6500'),
    ('beds_min', 1.5), ('baths_min', 7), ('no_ground_floor', 'yes'), ('areas', [99999]),
    ('areas', []), ('areas', [100, 100]), ('must_have', ['balcony']), ('sources', ['made-up']),
    ('move_in_by', '2026-02-30'), ('move_in_by', '20260925'), ('pause_s', 0),
])
def test_invalid_values_are_rejected_not_coerced(models, field, value):
    models['plan']['limits'][field] = value
    models['plan']['evidence']['limits.' + field] = 'Under $6500'
    with pytest.raises(preferences.PreferenceError):
        interpret()
    assert len(models['calls']) == 1


@pytest.mark.parametrize('bad', [None, [], {'unexpected': 'value'}])
def test_bad_plan_shape(models, bad):
    models['plan'] = bad
    with pytest.raises(preferences.PreferenceError):
        interpret()


def test_unquoted_evidence_is_rejected(models):
    models['plan']['evidence']['limits.price_max'] = 'Invented quote'
    with pytest.raises(preferences.PreferenceError, match='grounded'):
        interpret()


def test_truncated_json_is_rejected(models):
    models['finish'] = 'length'
    with pytest.raises(preferences.PreferenceError, match='complete'):
        interpret()


def test_invalid_jev_output_is_rejected(models):
    models['bad_answers'] = {'limits.price_max': {'noul': 1.5}}
    with pytest.raises(preferences.PreferenceError):
        interpret()


def test_contradictory_ranges_are_rejected(models):
    models['plan']['limits']['price_min'] = 7000
    models['plan']['evidence']['limits.price_min'] = 'Under $6500'
    with pytest.raises(preferences.PreferenceError, match='range'):
        interpret()


@pytest.mark.parametrize('text', ['', None, 12, 'x' * 2001])
def test_bad_input_never_calls_models(models, text):
    with pytest.raises(preferences.PreferenceError):
        preferences.interpret(text, DEFAULT_LIMITS, DEFAULT_WEIGHTS, {})
    assert not models['calls']


def test_api_preview_never_mutates_settings_or_starts_chrome(models, tmp_path):
    store = Store(tmp_path / 't.db')
    store.set_setting('limits', DEFAULT_LIMITS)

    def no_chrome():
        pytest.fail('A preference preview must never start Chrome')

    hunter = Hunter(store, chrome_factory=no_chrome)
    app = server.App(store, hunter)
    result = app.post('/api/preferences', {'text': TEXT, 'limits': DEFAULT_LIMITS,
                                         'weights': DEFAULT_WEIGHTS, 'tiers': {'115': 3}})
    assert result['limits']['price_max'] == 6500
    assert store.get_setting('limits') == DEFAULT_LIMITS
    assert hunter.job is None and store.last_run() is None


def test_no_supported_changes_skips_jev(models):
    models['plan'] = {'limits': {}, 'tiers': {}, 'priorities': [], 'evidence': {},
                      'unresolved': ['Commute time to an address is not supported.']}
    result = interpret()
    assert result['changes'] == [] and result['notes']
    assert len(models['calls']) == 1

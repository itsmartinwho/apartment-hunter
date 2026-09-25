"""Dedupe, SQLite store, vision and Jev validation with mocked HTTP. No paid API calls."""

import json

import pytest

from apartment_hunter import dedupe, jev, vision
from apartment_hunter.store import Store


def se(**kw):
    return {"id": "se:1", "source": "streeteasy", "kind": "unit", "street": "417 East 57th Street", "unit": "#7B",
            "beds": 1, "price": 4745, "lat": 40.7587, "lon": -73.9628, "photos": ["a"], "urls": {"streeteasy": "s"},
            "sqft": None, **kw}


def zl(**kw):
    return {"id": "z:9", "source": "zillow", "kind": "unit", "street": "417 E 57th St", "unit": "Apt 7B", "beds": 1,
            "price": 4745, "lat": 40.7588, "lon": -73.9627, "photos": ["b", "c", "d"], "urls": {"zillow": "z"},
            "sqft": 608, **kw}


def test_dedupe_merges_same_address_and_unit():
    merged = dedupe.merge([se(), zl()])
    assert len(merged) == 1
    one = merged[0]
    assert one["id"] == "se:1" and one["sqft"] == 608 and one["photos"] == ["b", "c", "d"]
    assert one["urls"] == {"zillow": "z", "streeteasy": "s"} and one["sources"] == ["streeteasy", "zillow"]


def test_dedupe_merges_by_location_when_units_differ_in_format():
    merged = dedupe.merge([se(unit=None), zl(unit=None)])
    assert len(merged) == 1


def test_dedupe_keeps_different_apartments_and_building_groups():
    group = zl(id="zb:X:1", kind="building_group", unit=None)
    assert len(dedupe.merge([se(), zl(unit="Apt 9C", price=6000), group])) == 3


def test_street_keys_normalize():
    assert dedupe.street_key("417 East 57th Street") == dedupe.street_key("417 E 57th St") == "417 e 57 st"
    assert dedupe.unit_key("Apt 7B") == dedupe.unit_key("#7B") == "7B"


def test_store_upsert_keeps_full_fields_over_map_fields(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.upsert([se(photos=["1", "2", "3"], sqft=700)]) == (1, 0)
    assert store.upsert([se(photos=["1"], sqft=None, price=4700)]) == (0, 1)
    row = store.get(["se:1"])[0]
    assert row["photos"] == ["1", "2", "3"] and row["sqft"] == 700 and row["price"] == 4700
    store.save_inspection("se:1", {"judgments": {"views": {"score": 0.5}}})
    assert store.all()[0]["inspection"]["judgments"]["views"]["score"] == 0.5
    store.set_setting("tiers", {"157": 1})
    assert store.get_setting("tiers") == {"157": 1} and store.get_setting("none", 5) == 5


def test_store_runs(tmp_path):
    store = Store(tmp_path / "t.db")
    run = store.add_run("search", {"price_max": 5000})
    assert store.last_run() is None
    store.finish_run(run, {"streeteasy": {"found": 3}})
    assert store.last_run()["stats"] == {"streeteasy": {"found": 3}}


GOOD_OBS = {"view": "skyline", "light": "bright", "windows": "large", "finishes": "modern", "condition": "new",
            "space": "open", "floor_cues": "high", "unit_photos": "actual unit", "red_flags": "none",
            "photos": [{"room": "Living room", "notes": "sofa"}]}


def test_vision_accepts_object_or_list_wrapper():
    assert vision.validate(json.dumps(GOOD_OBS))["view"] == "skyline"
    assert vision.validate(json.dumps([GOOD_OBS]))["photos"][0]["room"] == "Living room"


def test_vision_rejects_bad_output():
    with pytest.raises(vision.VisionError):
        vision.validate("I think it's nice")
    with pytest.raises(vision.VisionError):
        vision.validate(json.dumps({"view": "x"}))


def test_vision_observe_sends_images(monkeypatch):
    sent = {}

    def fake_post(url, key, body):
        sent.update(url=url, body=body)
        return {"choices": [{"message": {"content": json.dumps(GOOD_OBS)}}], "usage": {"prompt_tokens": 10}}

    monkeypatch.setenv("VISION_API_KEY", "k")
    monkeypatch.setattr(vision, "post_json", fake_post)
    obs, meta = vision.observe({"beds": 1, "kind": "unit"}, [(b"x", "image/webp")])
    assert obs["light"] == "bright" and meta["model"]
    parts = sent["body"]["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/webp;base64,")


def answers(**overrides):
    out = {}
    for qid, q in jev.QUESTIONS.items():
        if q["type"] == "noul":
            out[qid] = {"type": "noul", "noul": 0.9}
        else:
            n = len(q["criteria"])
            out[qid] = {"type": "score", "score": float(n - 1), "confidence": 1.0,
                        "probabilities": {str(i): float(i == n - 1) for i in range(n)}}
    out.update(overrides)
    return out


def test_jev_validate_normalizes_scores():
    out = jev.validate(answers())
    assert out["views"]["score"] == 1.0 and out["real_unit"] == {"p": 0.9}


@pytest.mark.parametrize("bad", [
    {"views": {"type": "score", "score": 1.0, "confidence": 1.0, "probabilities": {"0": 0.5, "1": 0.2}}},
    {"views": {"type": "score", "score": 9.0, "confidence": 1.0,
               "probabilities": {"0": 0.0, "1": 0.0, "2": 0.0, "3": 1.0}}},
    {"real_unit": {"type": "noul", "noul": 1.5}},
    {"light": None},
])
def test_jev_rejects_invalid_answers(bad):
    with pytest.raises(jev.JevError):
        jev.validate(answers(**bad))


def test_jev_judge_sends_one_request_with_all_questions(monkeypatch):
    calls = []

    def fake_post(url, key, body):
        calls.append(body)
        return {"model": "jev-1.13.0", "answers": answers(), "usage": {"input_tokens": 1}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(jev, "post_json", fake_post)
    judgments, meta = jev.judge({"kind": "unit", "title": "1 Main St #2"}, GOOD_OBS, 6)
    assert len(calls) == 1 and set(calls[0]["questions"]) == set(jev.QUESTIONS)
    assert "photos" not in calls[0]["state"]["photo_observations"]
    assert judgments["space"]["score"] == 1.0 and meta["model"] == "jev-1.13.0"


def test_interpret_sets_weights_from_words(monkeypatch):
    def fake_post(url, key, body):
        out = {}
        for cid in body["questions"]:
            level = {"light": 3, "subway": 0, "views": 2}.get(cid, 1)
            out[cid] = {"type": "score", "score": float(level), "confidence": 0.9,
                        "probabilities": {str(i): float(i == level) for i in range(4)}}
        return {"model": "jev-1.13.0", "answers": out}

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(jev, "post_json", fake_post)
    from apartment_hunter.criteria import DEFAULT_WEIGHTS
    out = jev.interpret("Lots of light matters most. I bike, so the subway does not matter. A view would be nice.",
                        DEFAULT_WEIGHTS)
    assert out["weights"]["light"] == 10 and out["weights"]["subway"] == 0 and out["weights"]["views"] == 6
    assert out["weights"]["price"] == DEFAULT_WEIGHTS["price"]
    assert {c["id"] for c in out["changes"]} == {"light", "subway", "views"}


def test_interpret_needs_text(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    with pytest.raises(jev.JevError):
        jev.interpret("   ", {})

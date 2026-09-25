"""Jev turns photo observations and listing facts into calibrated, typed judgments.

One request per listing asks every question together; the questions run in parallel on the same state.
Code combines the normalized scores with the user's weights (TypeSafe's composite scoring pattern).
"""

import math
import time

from .client import ModelError, post_json
from .config import settings
from .criteria import CRITERIA

URL = "https://api.typesafe.ai/v1/systemone"

QUESTIONS = {
    c["id"]: {"type": "score", "instructions": c["question"], "criteria": c["levels"]}
    for c in CRITERIA if c["pass"] == 2
}
QUESTIONS["floor_estimate"] = {
    "type": "score",
    "instructions": "Estimate how high this apartment is. Use `photo_observations.floor_cues`, "
                    "`photo_observations.view`, and `listing.unit`.",
    "criteria": [
        "Ground floor, garden level, or below street level",
        "Low floor, about floors 2 to 4: street trees and storefronts are close outside",
        "Middle floor, about floors 5 to 12: the view looks across at nearby buildings",
        "High floor, about floor 13 or above: the view looks over most rooftops",
    ],
}
QUESTIONS["real_unit"] = {
    "type": "noul",
    "instructions": "Do the photos show the actual apartment for rent, not renderings, a model unit, or only "
                    "building amenities? Use `photo_observations.unit_photos` and `listing.kind`.",
}


class JevError(RuntimeError):
    pass


def _finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def _score(qid, answer, top):
    probabilities = answer.get("probabilities") or {}
    score, confidence = answer.get("score"), answer.get("confidence")
    valid = (
        isinstance(probabilities, dict) and set(probabilities) == {str(i) for i in range(top + 1)}
        and all(_finite(v) and 0 <= v <= 1 for v in probabilities.values())
        and abs(sum(probabilities.values()) - 1) < 0.02
        and _finite(score) and -1e-6 <= score <= top + 1e-6
        and _finite(confidence) and 0 <= confidence <= 1
    )
    if not valid:
        raise JevError(f"Invalid Score answer for {qid}")
    return {"score": round(min(max(score / top, 0.0), 1.0), 4), "confidence": round(confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in probabilities.items()}}


def validate(answers, questions=None):
    """Check every answer's shape; normalize Scores to 0..1 by their top level."""
    if not isinstance(answers, dict):
        raise JevError("Jev returned invalid answers")
    out = {}
    for qid, question in (questions or QUESTIONS).items():
        answer = (answers or {}).get(qid)
        if not isinstance(answer, dict):
            raise JevError(f"Jev returned no answer for {qid}")
        if question["type"] == "noul":
            p = answer.get("noul")
            if not _finite(p) or not 0 <= p <= 1:
                raise JevError(f"Invalid Noul answer for {qid}")
            out[qid] = {"p": round(p, 4)}
        else:
            out[qid] = _score(qid, answer, len(question["criteria"]) - 1)
    return out


def state_for(listing, observations, photos_seen):
    detail = listing.get("detail") or {}
    return {
        "listing": {
            "kind": "one apartment" if listing.get("kind") == "unit" else "a building with several apartments",
            "address": listing.get("title"),
            "unit": listing.get("unit"),
            "neighborhood": listing.get("area_name"),
            "bedrooms": listing.get("beds"),
            "bathrooms": listing.get("baths"),
            "sqft": listing.get("sqft"),
            "rent": listing.get("price"),
            "photos_seen": photos_seen,
            "description": (detail.get("description") or "")[:1500] or None,
        },
        "photo_observations": {k: v for k, v in observations.items() if k != "photos"},
    }


def judge(listing, observations, photos_seen):
    """Returns (judgments, meta). Raises JevError; never invents a value."""
    s = settings()
    if not s["typesafe_key"]:
        raise JevError("Set TYPESAFE_API_KEY in .env for Jev judgments")
    body = {"model": s["typesafe_model"], "state": state_for(listing, observations, photos_seen),
            "questions": QUESTIONS}
    started = time.perf_counter()
    try:
        result = post_json(URL, s["typesafe_key"], body)
    except ModelError as error:
        raise JevError(str(error)) from None
    judgments = validate(result.get("answers"))
    meta = {"model": result.get("model"), "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": result.get("usage", {})}
    return judgments, meta


# Turning the renter's own words into slider weights. Level 1 ("not mentioned") keeps the current weight.
MEANINGS = {
    "price": "paying a low rent", "neighborhood": "living in a desirable neighborhood",
    "subway": "a short walk to the subway", "lines": "many subway lines nearby",
    "size": "a large apartment in square feet", "bedrooms": "more bedrooms", "floor": "living on a high floor",
    "move_in": "a move-in date that fits their timing", "deal": "free months or move-in deals",
    "views": "a good view", "light": "natural light", "windows": "big windows",
    "renovation": "a new or renovated apartment", "space": "an apartment that feels spacious",
}
PRIORITY_LEVELS = [
    "The renter says this does not matter to them",
    "The renter does not mention this",
    "The renter says this matters somewhat",
    "The renter says this matters a lot, or calls it a top priority",
]
LEVEL_WEIGHT = {0: 0, 2: 6, 3: 10}
MIN_CONFIDENCE = 0.45


def priority_questions():
    return {cid: {"type": "score", "criteria": PRIORITY_LEVELS,
                  "instructions": f"How much does the renter care about {meaning}? Use only `renter_text`."}
            for cid, meaning in MEANINGS.items()}


def interpret(text, weights):
    """Weights from a plain-language description. Unmentioned or uncertain criteria keep their weight."""
    s = settings()
    if not s["typesafe_key"]:
        raise JevError("Set TYPESAFE_API_KEY in .env for Jev judgments")
    text = (text or "").strip()
    if not text:
        raise JevError("Describe what matters to you first")
    questions = priority_questions()
    started = time.perf_counter()
    try:
        result = post_json(URL, s["typesafe_key"], {"model": s["typesafe_model"],
                                                    "state": {"renter_text": text[:2000]}, "questions": questions})
    except ModelError as error:
        raise JevError(str(error)) from None
    answers = validate(result.get("answers"), questions)
    out, changes = dict(weights), []
    for cid, answer in answers.items():
        probabilities = answer["probabilities"]
        level = int(max(probabilities, key=probabilities.get))
        if level not in LEVEL_WEIGHT or answer["confidence"] < MIN_CONFIDENCE:
            continue
        if out.get(cid) != LEVEL_WEIGHT[level]:
            changes.append({"id": cid, "from": out.get(cid), "to": LEVEL_WEIGHT[level],
                            "confidence": answer["confidence"]})
            out[cid] = LEVEL_WEIGHT[level]
    return {"weights": out, "changes": changes, "model": result.get("model"),
            "latency_ms": round((time.perf_counter() - started) * 1000)}

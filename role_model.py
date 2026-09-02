"""
Lazy loader for the trained role classifier (models/role_classifier.joblib).

The artifact is committed to the repo; scikit-learn is only needed when the
model is actually used. roles.py falls back to keyword-profile matching when
the model or sklearn is unavailable — the pipeline never hard-depends on it.
"""

import os

_MODEL = None
_MODEL_TRIED = False

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "role_classifier.joblib")

# Serving decision rule. These are DEFAULTS: if the artifact records its own
# min_confidence / min_margin, those win, so the model and the rule it
# was validated under can never drift apart.
#
# Why a margin and not just a threshold: TF-IDF probabilities over 8 classes on
# a small corpus are inherently flat. A real resume that the model ranks
# correctly still often peaks around 0.25-0.45. The old absolute-only gate of
# 0.45 therefore rejected essentially every genuine upload and the "trained
# classifier" never ran in production. A confident top-1 is better identified
# by how far it leads the runner-up.
MIN_CONFIDENCE = 0.40
MIN_MARGIN = 0.10


def ml_available() -> bool:
    global _MODEL, _MODEL_TRIED
    if _MODEL_TRIED:
        return _MODEL is not None
    _MODEL_TRIED = True
    try:
        import joblib  # noqa: F401
        if os.path.exists(MODEL_PATH):
            _MODEL = joblib.load(MODEL_PATH)
        else:
            _MODEL = None
    except Exception:                          # pragma: no cover
        _MODEL = None
    return _MODEL is not None


def _thresholds():
    """(min_confidence, min_margin) — artifact-provided values take priority."""
    if not ml_available():
        return MIN_CONFIDENCE, MIN_MARGIN
    return (
        float(_MODEL.get("min_confidence", MIN_CONFIDENCE)),
        float(_MODEL.get("min_margin", MIN_MARGIN)),
    )


def predict_role(text: str):
    """Return (label, confidence) from the trained model, or None."""
    if not text or not text.strip() or not ml_available():
        return None
    proba = _MODEL["pipeline"].predict_proba([text])[0]
    labels = _MODEL["pipeline"].classes_
    best = int(proba.argmax())
    return str(labels[best]), float(proba[best])


def predict_role_detailed(text: str):
    """(label, top_probability, margin_over_runner_up) or None.

    The margin is what makes the ML vote trustworthy on flat multi-class
    distributions — see the MIN_MARGIN note above.
    """
    if not text or not text.strip() or not ml_available():
        return None
    proba = _MODEL["pipeline"].predict_proba([text])[0]
    labels = _MODEL["pipeline"].classes_
    order = sorted(range(len(proba)), key=lambda i: -proba[i])
    top = order[0]
    runner_up = float(proba[order[1]]) if len(order) > 1 else 0.0
    return str(labels[top]), float(proba[top]), float(proba[top]) - runner_up


def accepts(top_p: float, margin: float) -> bool:
    """Should the ML vote be trusted over the keyword fallback?"""
    min_conf, min_margin = _thresholds()
    return top_p >= min_conf or margin >= min_margin


def model_metadata():
    if ml_available():
        return {k: v for k, v in _MODEL.items() if k != "pipeline"}
    return None

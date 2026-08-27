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

# Below this confidence the ML vote is ignored and keywords take over.
MIN_CONFIDENCE = 0.45


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


def predict_role(text: str):
    """Return (label, confidence) from the trained model, or None."""
    if not text or not ml_available():
        return None
    proba = _MODEL["pipeline"].predict_proba([text])[0]
    labels = _MODEL["pipeline"].classes_
    best = int(proba.argmax())
    return str(labels[best]), float(proba[best])


def model_metadata():
    if ml_available():
        return {k: v for k, v in _MODEL.items() if k != "pipeline"}
    return None

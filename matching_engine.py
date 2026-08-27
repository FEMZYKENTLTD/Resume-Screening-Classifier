"""
Semantic matching engine (OPTIONAL, feature-flagged).

Enabled when ENABLE_SEMANTIC=1 AND the heavy ML stack is installed:
    pip install sentence-transformers scikit-learn

The base pipeline (keyword overlap + skill extraction) never depends on
this module, which keeps the docker images lean. When enabled, the worker
blends the semantic score with the keyword score (see tasks.py) and stores
the full breakdown in ResumeResult.match_details.
"""

import re

from skills import extract_skills

_MODEL = None
_MODEL_NAME = "all-MiniLM-L6-v2"
WEAK_ALIGNMENT_THRESHOLD = 0.65
_MAX_CHARS = 5000  # embeddings are sentence-scale; cap payload for speed


def semantic_available() -> bool:
    """True if the heavy ML dependency imports cleanly."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


def load_embedding_model():
    """Lazy singleton model loader (~90 MB download on first use)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(_MODEL_NAME)
    return _MODEL


def _cosine(a, b):
    """Pure-numpy cosine similarity — no sklearn needed."""
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def calculate_match(resume_text: str, jd_text: str, model=None):
    """Semantic (embedding) match + skill-gap analysis.

    Returns a JSON-serializable dict. `model` is injectable so unit tests
    can pass a lightweight stand-in instead of downloading the real model.
    """
    if model is None:
        model = load_embedding_model()

    resume_text = (resume_text or "")[:_MAX_CHARS]
    jd_text = (jd_text or "")[:_MAX_CHARS]

    embeddings = model.encode([resume_text, jd_text])
    similarity_percentage = round(float(_cosine(embeddings[0], embeddings[1])) * 100, 2)

    resume_skills = extract_skills(resume_text)
    jd_skills = extract_skills(jd_text)
    matched_skills = jd_skills & resume_skills
    missing_skills = jd_skills - resume_skills
    skill_coverage = round(len(matched_skills) / len(jd_skills) * 100, 2) if jd_skills else 0

    # Contextual gap analysis: JD sentences not reflected in the resume
    jd_sentences = [s.strip() for s in re.split(r"[.\n]", jd_text) if s.strip()]
    resume_sentences = [s.strip() for s in re.split(r"[.\n]", resume_text) if s.strip()]
    semantic_gaps = []

    if jd_sentences and resume_sentences:
        resume_embeddings = model.encode(resume_sentences)
        for jd_sentence in jd_sentences:
            jd_emb = model.encode([jd_sentence])[0]
            best = max((_cosine(jd_emb, r) for r in resume_embeddings), default=0)
            if best < WEAK_ALIGNMENT_THRESHOLD:
                semantic_gaps.append(
                    f'JD requirement not strongly reflected: "{jd_sentence}"'
                )

    return {
        "algorithm": "semantic+keyword",
        "semantic_score": similarity_percentage,
        "skill_coverage": skill_coverage,
        "matched_skills": sorted(matched_skills),
        "missing_skills": sorted(missing_skills),
        "resume_skills": sorted(resume_skills),
        "jd_skills": sorted(jd_skills),
        "semantic_gaps": semantic_gaps[:10],
    }

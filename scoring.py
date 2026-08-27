"""
Shared scoring logic — single source of truth used by the Celery worker
and the Streamlit dashboard (so both can never disagree again).
"""

import re

TOKEN_RE = re.compile(r"\b\w+\b")


def overlap_score(resume_text: str, jd: str):
    """Keyword overlap between resume and JD, as a percentage 0-100.

    Returns (score_percent, matched_words). Regex tokenization keeps
    punctuation like 'SQL,' or '(docker)' from poisoning matches.
    """
    jd_words = set(TOKEN_RE.findall(jd.lower()))
    resume_words = set(TOKEN_RE.findall(resume_text.lower()))
    overlap = sorted(jd_words & resume_words)
    score = int(round(100 * len(overlap) / len(jd_words))) if jd_words else 0
    return score, overlap

"""
Lightweight keyword-based skill extraction shared by the Celery worker
and the Streamlit dashboard.

This intentionally has NO heavy dependencies (no torch / transformers)
so it can run in every container. Semantic/embedding-based matching is
on the roadmap (see matching_engine.py for the prototype).
"""

import re

TECH_SKILLS_DB = [
    "python", "sql", "java", "c++", "javascript", "typescript", "php", "ruby", "go",
    "machine learning", "deep learning", "nlp", "computer vision", "pandas", "numpy",
    "scikit-learn", "tensorflow", "keras", "pytorch", "docker", "kubernetes", "aws",
    "azure", "gcp", "git", "github", "ci/cd", "linux", "terraform", "mysql", "mongodb",
    "spark", "hadoop", "snowflake", "bigquery", "django", "flask", "fastapi", "react",
    "angular", "node.js", "html", "css", "rest api", "power bi", "tableau", "excel",
]


def extract_skills(text: str) -> set:
    """Return the set of known tech skills found in `text` (title-cased)."""
    text_lower = text.lower()
    found = set()
    for skill in TECH_SKILLS_DB:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
            found.add(skill.title())
    return found

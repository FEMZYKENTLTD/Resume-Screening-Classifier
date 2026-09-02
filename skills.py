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


# Canonical display names. str.title() mangles these ("Node.Js", "Ci/Cd",
# "Rest Api"), which then leaks into the UI, the CSV export and the PDF report.
_DISPLAY_NAMES = {
    "c++": "C++", "ci/cd": "CI/CD", "node.js": "Node.js", "rest api": "REST API",
    "sql": "SQL", "nlp": "NLP", "aws": "AWS", "gcp": "GCP", "html": "HTML",
    "css": "CSS", "php": "PHP", "mysql": "MySQL", "mongodb": "MongoDB",
    "postgresql": "PostgreSQL", "javascript": "JavaScript",
    "typescript": "TypeScript", "scikit-learn": "scikit-learn",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "fastapi": "FastAPI",
    "power bi": "Power BI", "bigquery": "BigQuery", "github": "GitHub",
    "numpy": "NumPy", "keras": "Keras", "django": "Django", "flask": "Flask",
    "react": "React", "angular": "Angular", "docker": "Docker",
    "kubernetes": "Kubernetes", "terraform": "Terraform", "linux": "Linux",
    "spark": "Spark", "hadoop": "Hadoop", "snowflake": "Snowflake",
    "tableau": "Tableau", "excel": "Excel", "python": "Python", "java": "Java",
    "ruby": "Ruby", "go": "Go", "git": "Git", "azure": "Azure",
    "pandas": "pandas",
}


def display_name(skill: str) -> str:
    """Human-facing label for a skill key."""
    return _DISPLAY_NAMES.get(skill.lower(), skill.title())


def _skill_pattern(skill: str) -> str:
    r"""Word-boundary pattern that survives non-word trailing characters.

    ``\bc\+\+\b`` can never match: '+' is a non-word char, so a trailing
    ``\b`` demands a word char immediately after it. Same trap for 'node.js'
    and 'ci/cd'. Anchor with ``\b`` only where the skill really starts/ends
    with a word character, and use lookarounds otherwise.
    """
    escaped = re.escape(skill)
    left = "\\b" if skill[0].isalnum() else "(?<![\\w+#])"
    right = "\\b" if skill[-1].isalnum() else "(?![\\w+#])"
    return left + escaped + right


_COMPILED = [(s, re.compile(_skill_pattern(s), re.IGNORECASE))
             for s in TECH_SKILLS_DB]


def extract_skills(text: str) -> set:
    """Return the set of known tech skills found in `text` (display-cased)."""
    if not text:
        return set()
    return {display_name(skill) for skill, rx in _COMPILED if rx.search(text)}

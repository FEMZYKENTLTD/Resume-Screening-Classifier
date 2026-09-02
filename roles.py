"""
Role / industry classification — two tiers:

1. Trained ML model (TF-IDF + logistic regression, see
   training/train_role_classifier.py) when the artifact + sklearn are present.
2. Keyword-profile matching fallback (deterministic, dependency-free).

Returns 'General / Uncategorized' when neither reaches its confidence bar.
"""

import re
from collections import Counter

import role_model

ROLE_PROFILES = {
    "Data Science / ML": [
        "machine learning", "deep learning", "nlp", "computer vision",
        "pandas", "numpy", "scikit-learn", "tensorflow", "keras", "pytorch",
        "data science", "model", "prediction", "analytics", "statistics",
    ],
    "Backend Engineering": [
        "api", "rest", "fastapi", "django", "flask", "node.js", "microservices",
        "database", "postgres", "mysql", "mongodb", "redis", "backend", "server",
    ],
    "Frontend Engineering": [
        "react", "angular", "vue", "javascript", "typescript", "html", "css",
        "frontend", "ui", "ux", "responsive", "tailwind", "webpack",
    ],
    "DevOps / Cloud": [
        "docker", "kubernetes", "aws", "azure", "gcp", "terraform", "ci/cd",
        "jenkins", "linux", "devops", "cloud", "infrastructure", "ansible",
    ],
    "Data Engineering": [
        "spark", "hadoop", "airflow", "etl", "pipeline", "snowflake",
        "bigquery", "kafka", "data warehouse", "dbt", "data lake",
    ],
    # Distinct from Data Science / ML: BI and reporting work, not modelling.
    # Without this, analyst resumes fell through to "General / Uncategorized".
    "Data Analytics / BI": [
        "data analyst", "business intelligence", "power bi", "tableau",
        "looker", "dashboard", "excel", "reporting", "sql", "kpi",
        "google analytics", "data visualization", "spreadsheet",
    ],
    "Mobile Development": [
        "android", "ios", "swift", "kotlin", "flutter", "react native",
        "mobile", "xcode",
    ],
    "QA / Testing": [
        "testing", "qa", "selenium", "cypress", "unit test", "automation",
        "quality assurance", "test cases", "pytest",
    ],
    "Cybersecurity": [
        "security", "penetration", "vulnerability", "firewall", "siem",
        "encryption", "soc", "infosec", "compliance",
    ],
}

_MIN_HITS = 2  # minimum distinct profile keywords to trust a classification


def classify_role_keywords(text: str) -> str:
    """Keyword-profile classifier (the pre-ML baseline — kept as fallback)."""
    if not text:
        return "General / Uncategorized"

    text_lower = text.lower()
    hits = Counter()
    for role, keywords in ROLE_PROFILES.items():
        count = sum(
            1 for kw in keywords
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower)
        )
        if count:
            hits[role] = count

    if not hits or hits.most_common(1)[0][1] < _MIN_HITS:
        return "General / Uncategorized"
    return hits.most_common(1)[0][0]


def classify_role(text: str) -> str:
    """Best role label for the resume text: ML model first, keywords second."""
    return classify_role_with_method(text)[0]


def classify_role_with_method(text: str):
    """(label, method, confidence_or_None) — used for reporting/debugging.

    Accepts the ML vote when it is either absolutely confident OR clearly
    ahead of the runner-up (see role_model.MIN_MARGIN). Keyword profiles
    remain the fallback, and any failure inside the ML path degrades to them
    rather than propagating — the API contract promises graceful degradation.
    """
    try:
        detailed = role_model.predict_role_detailed(text)
    except Exception:
        detailed = None

    if detailed is not None:
        label, top_p, margin = detailed
        if role_model.accepts(top_p, margin):
            return label, "ml-model", round(top_p, 4)

    return classify_role_keywords(text), "keyword-profiles", None

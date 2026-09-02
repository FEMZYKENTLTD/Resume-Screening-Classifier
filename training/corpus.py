"""
Reproducible resume corpus generator for the role classifier.

WHY A GENERATOR INSTEAD OF A HAND-WRITTEN LIST
----------------------------------------------
The original corpus was 56 short, keyword-dense blurbs like:

    "Built machine learning models with pandas numpy scikit-learn..."

Real resumes do not look like that. They open with a name and a contact line,
carry a title, a summary, dated employment history with employer names, a
skills line, and a degree. All of that is *distractor text* that dilutes the
TF-IDF signal. The consequence was measured and documented in
train_role_classifier.py: the model ranked the right label first but peaked at
0.26-0.30 confidence, so the serving threshold rejected it and every real
upload silently fell back to keyword profiles.

This module closes the train/serve gap properly. It assembles documents from
role-specific vocabulary plus the SAME generic scaffolding every resume has,
so the classifier is forced to learn the discriminative tokens rather than
memorising short blurbs.

Design rules that keep the evaluation honest:

  * Everything is seeded, so `python -m training.train_role_classifier` is
    byte-reproducible.
  * make_dataset(split="train") and split="test" use disjoint RNG streams AND
    disjoint pools of names, employers, cities and phrasings. A test document
    can never be a near-duplicate of a training document.
  * The generator only supplies SURFACE realism. It cannot invent genuine
    signal, so the real demo PDFs remain the final arbiter and are asserted
    in the test suite.

Usage:
    from training.corpus import make_dataset, ROLES
    train = make_dataset(split="train", per_role=40)
    test  = make_dataset(split="test",  per_role=10)
"""

from __future__ import annotations

import random

# --------------------------------------------------------------------------
# Role-discriminative vocabulary. These are the tokens that SHOULD drive the
# decision. Kept deliberately close to how practitioners actually write them.
# --------------------------------------------------------------------------

ROLES: dict[str, dict[str, list[str]]] = {
    "Data Science / ML": {
        "titles": [
            "Data Scientist", "Senior Data Scientist", "Machine Learning Engineer",
            "ML Engineer", "Applied Scientist", "Research Scientist (ML)",
        ],
        "skills": [
            "Python", "pandas", "NumPy", "scikit-learn", "PyTorch", "TensorFlow",
            "Keras", "XGBoost", "NLP", "transformers", "computer vision",
            "statistics", "A/B testing", "feature engineering", "MLflow",
            "hyperparameter tuning", "cross-validation", "SQL",
        ],
        "verbs": [
            "trained and deployed {skill} models for churn prediction",
            "built {skill} pipelines that lifted conversion by {pct}%",
            "ran {skill} experiments and shipped the winning variant",
            "reduced model inference latency by {pct}% using {skill}",
            "owned feature engineering and {skill} model evaluation",
            "productionised a recommendation model with {skill}",
            "monitored model drift and retraining with {skill}",
        ],
    },
    "Data Engineering": {
        "titles": [
            "Data Engineer", "Senior Data Engineer", "Analytics Engineer",
            "Big Data Engineer", "Data Platform Engineer",
        ],
        "skills": [
            "Apache Airflow", "Spark", "dbt", "Kafka", "Snowflake", "BigQuery",
            "Redshift", "ETL", "ELT", "data warehouse", "data lake",
            "star schema", "Kimball", "Dataflow", "partitioning", "SQL", "Python",
        ],
        "verbs": [
            "built {skill} pipelines processing {n}M rows daily",
            "migrated legacy ETL jobs to {skill}",
            "modelled the warehouse in {skill} cutting query cost by {pct}%",
            "orchestrated ingestion with {skill} across {n} sources",
            "implemented {skill} tests catching schema drift before release",
            "designed {skill} ingestion for clickstream events",
            "tuned {skill} jobs and reduced runtime by {pct}%",
        ],
    },
    "Data Analytics / BI": {
        "titles": [
            "Data Analyst", "Business Intelligence Analyst", "Product Analyst",
            "Reporting Analyst", "Senior Data Analyst", "Insights Analyst",
        ],
        "skills": [
            "SQL", "Power BI", "Tableau", "Looker", "Excel", "dashboards",
            "KPI reporting", "Google Analytics", "data visualization",
            "cohort analysis", "pivot tables", "DAX", "stakeholder reporting",
        ],
        "verbs": [
            "built {skill} dashboards used by {n} stakeholders weekly",
            "automated monthly reporting in {skill} saving {n} hours a month",
            "ran {skill} cohort analysis that informed pricing",
            "defined KPI definitions and {skill} scorecards",
            "delivered self-serve {skill} reporting for commercial teams",
            "translated business questions into {skill} analyses",
        ],
    },
    "Backend Engineering": {
        "titles": [
            "Backend Engineer", "Senior Backend Engineer", "Software Engineer (Backend)",
            "API Engineer", "Platform Engineer",
        ],
        "skills": [
            "FastAPI", "Django", "Flask", "Node.js", "Express", "REST API",
            "GraphQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Celery",
            "microservices", "RabbitMQ", "gRPC", "database migrations",
        ],
        "verbs": [
            "designed {skill} services handling {n}k requests per minute",
            "built {skill} endpoints with token authentication",
            "cut p99 latency by {pct}% by adding {skill} caching",
            "decomposed a monolith into {skill}",
            "owned schema design and {skill} migrations",
            "implemented idempotent payment flows with {skill}",
        ],
    },
    "Frontend Engineering": {
        "titles": [
            "Frontend Engineer", "Senior Frontend Developer", "UI Engineer",
            "Web Developer", "Frontend Developer",
        ],
        "skills": [
            "React", "Vue", "Angular", "TypeScript", "JavaScript", "HTML", "CSS",
            "Tailwind", "Next.js", "Redux", "Vite", "Webpack", "responsive design",
            "accessibility", "design systems", "Jest",
        ],
        "verbs": [
            "built responsive {skill} interfaces for {n}k monthly users",
            "improved Lighthouse performance by {pct}% using {skill}",
            "created a reusable {skill} component library",
            "migrated a legacy codebase to {skill}",
            "implemented WCAG accessibility fixes across {skill} views",
            "reduced bundle size by {pct}% with {skill} code splitting",
        ],
    },
    "DevOps / Cloud": {
        "titles": [
            "DevOps Engineer", "Site Reliability Engineer", "Cloud Engineer",
            "Platform Reliability Engineer", "Infrastructure Engineer",
        ],
        "skills": [
            "Docker", "Kubernetes", "Terraform", "Ansible", "AWS", "Azure", "GCP",
            "Jenkins", "GitHub Actions", "CI/CD", "Linux", "Prometheus", "Grafana",
            "Helm", "infrastructure as code", "autoscaling",
        ],
        "verbs": [
            "automated provisioning with {skill} across {n} environments",
            "ran {skill} clusters with {pct}% uptime",
            "built {skill} pipelines cutting deploy time by {pct}%",
            "reduced cloud spend by {pct}% through {skill} rightsizing",
            "led incident response and {skill} observability",
            "hardened {skill} images and rotated secrets",
        ],
    },
    "Mobile Development": {
        "titles": [
            "Mobile Developer", "Android Developer", "iOS Engineer",
            "Senior Mobile Engineer", "Cross-platform Mobile Developer",
        ],
        "skills": [
            "Kotlin", "Swift", "SwiftUI", "Flutter", "Dart", "React Native",
            "Android SDK", "Jetpack Compose", "Xcode", "MVVM", "Play Store",
            "App Store", "push notifications", "offline sync",
        ],
        "verbs": [
            "shipped {skill} apps with {n}k downloads",
            "rebuilt the app architecture in {skill}",
            "cut cold start time by {pct}% in {skill}",
            "implemented offline-first sync using {skill}",
            "released {skill} builds through automated store pipelines",
            "raised crash-free sessions to {pct}% with {skill} instrumentation",
        ],
    },
    "QA / Testing": {
        "titles": [
            "QA Engineer", "QA Automation Engineer", "SDET",
            "Test Automation Lead", "Quality Assurance Analyst",
        ],
        "skills": [
            "Selenium", "Cypress", "Playwright", "pytest", "JUnit",
            "test automation", "regression testing", "unit test coverage",
            "quality assurance", "test cases", "load testing", "CI test suites",
        ],
        "verbs": [
            "automated {n} regression cases with {skill}",
            "raised test coverage to {pct}% using {skill}",
            "built {skill} suites gating every release",
            "cut manual test cycles by {pct}% through {skill}",
            "designed {skill} smoke tests for critical journeys",
            "owned defect triage and {skill} reporting",
        ],
    },
    "Cybersecurity": {
        "titles": [
            "Security Analyst", "Cybersecurity Engineer", "SOC Analyst",
            "Information Security Engineer", "Penetration Tester",
        ],
        "skills": [
            "SIEM", "SOC", "penetration testing", "vulnerability management",
            "firewall", "encryption", "incident response", "threat hunting",
            "ISO 27001", "SOC 2", "compliance", "security audits", "Burp Suite",
        ],
        "verbs": [
            "tuned {skill} rules cutting false positives by {pct}%",
            "led {skill} engagements across {n} applications",
            "reduced mean time to detect by {pct}% with {skill}",
            "ran {skill} assessments and tracked remediation",
            "implemented {skill} controls ahead of audit",
            "responded to security incidents using {skill} playbooks",
        ],
    },
}

# --------------------------------------------------------------------------
# Generic scaffolding. This is the SAME for every role on purpose — it is the
# realistic noise that the original blurb corpus lacked entirely.
# --------------------------------------------------------------------------

_FIRST_TRAIN = [
    "Adaeze", "Chinedu", "Emeka", "Ngozi", "Yemi", "Tobi", "Kelechi", "Aisha",
    "Musa", "Blessing", "Segun", "Hassan", "Damilola", "Folake", "Ifeoma",
    "Bashir", "Chioma", "Olumide", "Halima", "Obinna",
]
_LAST_TRAIN = [
    "Okafor", "Adeyemi", "Bello", "Nwosu", "Yusuf", "Ola", "Eze", "Danjuma",
    "Ade", "Salami", "Fashola", "Okoro", "Abubakar", "Ogun", "Udo",
]
_FIRST_TEST = [
    "Temitope", "Uche", "Zainab", "Ikenna", "Funmi", "Sadiq", "Amaka",
    "Gbenga", "Rukayat", "Chidi", "Nnamdi", "Bukola",
]
_LAST_TEST = [
    "Ogundipe", "Nnaji", "Idris", "Coker", "Balogun", "Ezenwa", "Lawal",
    "Onyeka", "Adebayo", "Sowande",
]

_CITIES_TRAIN = ["Lagos", "Abuja", "Ibadan", "Port Harcourt", "Kano", "Enugu"]
_CITIES_TEST = ["Benin City", "Kaduna", "Jos", "Uyo", "Owerri", "Warri"]

_EMPLOYERS_TRAIN = [
    "Paystack", "Flutterwave", "Interswitch", "Andela", "Kuda Bank", "Jumia",
    "Konga", "Cowrywise", "PiggyVest", "TeamApt",
]
_EMPLOYERS_TEST = [
    "Moniepoint", "Bamboo", "Chipper Cash", "Termii", "SeamlessHR",
    "Reliance Health", "Helium Health",
]

_SCHOOLS = [
    "University of Lagos", "University of Ibadan", "Ahmadu Bello University",
    "Obafemi Awolowo University", "Covenant University", "University of Nigeria Nsukka",
    "Federal University of Technology Akure", "Bayero University Kano",
    "Yaba College of Technology", "University of Benin",
]
_DEGREES = [
    "B.Sc Computer Science", "B.Eng Computer Engineering", "B.Sc Statistics",
    "B.Sc Mathematics", "HND Computer Science", "M.Sc Computer Science",
    "B.Sc Information Systems", "B.Tech Information Technology",
    "B.Sc Economics", "M.Sc Data Science",
]

# Soft-skill filler that appears on nearly every real CV and carries no signal.
_FILLER = [
    "Strong communication and stakeholder management skills.",
    "Comfortable working in agile cross-functional teams.",
    "Mentored junior engineers and ran internal knowledge sessions.",
    "Experience working in fast-paced startup environments.",
    "Detail-oriented with a bias for shipping.",
    "Collaborated closely with product and design.",
    "Available for remote or hybrid roles.",
    "References available on request.",
]

_SUMMARY_TEMPLATES = [
    "{years} years of experience as a {title}.",
    "{title} with {years}+ years delivering production systems.",
    "Results-driven {title} with {years} years of hands-on experience.",
    "Experienced {title} ({years} years) focused on measurable impact.",
]


def _pools(split: str):
    if split == "train":
        return _FIRST_TRAIN, _LAST_TRAIN, _CITIES_TRAIN, _EMPLOYERS_TRAIN
    return _FIRST_TEST, _LAST_TEST, _CITIES_TEST, _EMPLOYERS_TEST


def make_resume(role: str, rng: random.Random, split: str = "train") -> str:
    """Assemble one resume-shaped document for `role`."""
    spec = ROLES[role]
    firsts, lasts, cities, employers = _pools(split)

    name = f"{rng.choice(firsts)} {rng.choice(lasts)}"
    title = rng.choice(spec["titles"])
    city = rng.choice(cities)
    years = rng.randint(2, 12)
    email = f"{name.split()[0].lower()}.{name.split()[1].lower()}@example.com"
    phone = f"+234 {rng.randint(700, 909)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"

    skills = rng.sample(spec["skills"], k=min(len(spec["skills"]), rng.randint(6, 10)))

    bullets = []
    for verb in rng.sample(spec["verbs"], k=min(len(spec["verbs"]), rng.randint(3, 5))):
        bullets.append("- " + verb.format(
            skill=rng.choice(skills),
            pct=rng.randint(10, 60),
            n=rng.randint(2, 90),
        ))

    jobs = []
    end = 2026 - rng.randint(0, 2)
    for _ in range(rng.randint(1, 3)):
        start = end - rng.randint(1, 4)
        jobs.append(f"{rng.choice(employers)} — {title}  ({start}–{end})")
        end = start

    parts = [
        name,
        title,
        f"{email} | {phone} | {city}, Nigeria",
        "",
        "SUMMARY",
        rng.choice(_SUMMARY_TEMPLATES).format(title=title, years=years),
        rng.choice(_FILLER),
        "",
        "SKILLS",
        ", ".join(skills) + ".",
        "",
        "EXPERIENCE",
    ]
    parts.extend(jobs)
    parts.extend(bullets)
    parts.extend([
        "",
        "EDUCATION",
        f"{rng.choice(_DEGREES)}, {rng.choice(_SCHOOLS)}.",
    ])
    if rng.random() < 0.5:
        parts.append(rng.choice(_FILLER))

    return "\n".join(parts)


def make_dataset(split: str = "train", per_role: int = 40, seed: int | None = None):
    """Generate [(text, label), ...].

    Train and test use different base seeds AND disjoint surface pools, so a
    test document is never a near-duplicate of a training document.
    """
    if seed is None:
        seed = 20260902 if split == "train" else 77313
    rows = []
    for offset, (role, _) in enumerate(sorted(ROLES.items())):
        rng = random.Random(seed + offset * 1013)
        for _ in range(per_role):
            rows.append((make_resume(role, rng, split=split), role))
    return rows

"""
Train the role / industry classifier.

Real supervised model: TF-IDF (word uni/bi-grams) + multinomial logistic
regression on a curated resume-style corpus. Reproducible:

    python -m training.train_role_classifier

Artifacts: models/role_classifier.joblib  (committed; auto-used by roles.py)

The curated corpus is intentionally small and transparent so the labels are
auditable — extend DATA with real (pseudonymized) resumes to improve it.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = [
    # Data Science / ML
    ("Built machine learning models with pandas numpy scikit-learn. Deep learning with tensorflow and keras. NLP and computer vision projects, statistical prediction analytics for data science team.", "Data Science / ML"),
    ("Data scientist with 5 years in predictive modeling, machine learning pipelines, pytorch, nlp transformers, statistics, ab testing and analytics dashboards.", "Data Science / ML"),
    ("Trained deep learning computer vision models using tensorflow keras numpy pandas. Published machine learning research on nlp classification with scikit-learn.", "Data Science / ML"),
    ("Applied statistics, regression models and machine learning for churn prediction. Python, pandas, numpy, scikit-learn, data science reporting analytics.", "Data Science / ML"),
    ("ML engineer deploying deep learning and nlp models to production. Model evaluation, feature engineering, transformers, pytorch, prediction services.", "Data Science / ML"),
    ("Analyst turned data scientist: machine learning, statistics, computer vision experiments, tensorflow, pandas, numpy, analytics and model monitoring.", "Data Science / ML"),
    ("Recommendation systems with machine learning, collaborative filtering, nlp embeddings, scikit-learn, pandas, deep learning research prototypes.", "Data Science / ML"),
    # Backend Engineering
    ("Backend engineer building REST APIs with FastAPI Django Flask. PostgreSQL MySQL MongoDB database design, redis caching, microservices on the server side.", "Backend Engineering"),
    ("Designed microservices in Node.js and Python, REST API development, database modeling with postgres, redis message queues, backend deployments.", "Backend Engineering"),
    ("Server-side development: django rest framework, fastapi, flask, mysql and postgres schema optimization, api authentication, backend integrations.", "Backend Engineering"),
    ("Backend developer with 8 years building APIs, microservices and databases. Node.js, express, mongodb, postgres, redis, rest design.", "Backend Engineering"),
    ("Maintained high-throughput REST API microservices, postgres and mysql replication, redis caching layer, flask and django backend services.", "Backend Engineering"),
    ("Payments backend: fastapi microservices, postgres transactions, rest api contracts, node.js workers, database migrations, api versioning.", "Backend Engineering"),
    ("Python backend engineer: django ORM corporate applications, mysql database administration, rest API endpoints, server maintenance.", "Backend Engineering"),
    # Frontend Engineering
    ("Frontend developer building responsive UI with React, javascript, typescript, html and css. UX-focused components, tailwind, webpack tooling.", "Frontend Engineering"),
    ("Created single-page applications in React and Vue with typescript. CSS animations, responsive design, ui ux collaboration, frontend testing.", "Frontend Engineering"),
    ("Frontend engineer: angular enterprise apps, javascript es6, typescript, html css accessibility, ui component libraries, ux reviews.", "Frontend Engineering"),
    ("Design-driven frontend work: react hooks, css grid responsive layouts, javascript performance, webpack builds, ui polish and ux research.", "Frontend Engineering"),
    ("Migrated legacy jquery to modern react typescript frontend. html semantics, css architecture, ui design system components.", "Frontend Engineering"),
    ("Mobile-first responsive web apps, vue and react, frontend state management, javascript typescript unit testing, css ux improvements.", "Frontend Engineering"),
    ("Frontend specialist: pixel-perfect css, react performance profiling, javascript typescript tooling, ui ux accessibility audits.", "Frontend Engineering"),
    # DevOps / Cloud
    ("DevOps engineer automating infrastructure with terraform and ansible. Docker kubernetes clusters on AWS, ci/cd jenkins pipelines, linux administration.", "DevOps / Cloud"),
    ("Cloud infrastructure on azure and gcp: kubernetes, docker, ci/cd pipelines, terraform modules, linux servers, devops monitoring.", "DevOps / Cloud"),
    ("Managed AWS cloud infrastructure, kubernetes workloads, docker images, ci/cd with jenkins and github actions, terraform iac, devops culture.", "DevOps / Cloud"),
    ("Site reliability: linux hardening, kubernetes autoscaling, docker, aws cost optimization, ci/cd automation, ansible, devops incident response.", "DevOps / Cloud"),
    ("Built ci/cd pipelines and container platforms: docker, kubernetes helm charts, terraform for gcp, linux, cloud devops enablement.", "DevOps / Cloud"),
    ("DevOps lead: migrated on-prem to AWS cloud, kubernetes operators, docker security scanning, jenkins ci/cd, terraform provisioning.", "DevOps / Cloud"),
    ("Infrastructure as code with terraform on azure, kubernetes clusters, docker registries, ci/cd automation, cloud devops tooling.", "DevOps / Cloud"),
    # Data Engineering
    ("Data engineer building ETL pipelines with Airflow and Spark. Snowflake data warehouse, kafka streaming, bigquery, dbt models, data lake storage.", "Data Engineering"),
    ("Designed data pipelines: spark batch jobs, kafka streams, airflow orchestration, snowflake warehouse, etl from hadoop data lake to bigquery.", "Data Engineering"),
    ("Maintained ETL flows into a data warehouse using dbt and airflow. Spark transformations, kafka events, snowflake, bigquery reporting tables.", "Data Engineering"),
    ("Streaming data platform: kafka, spark structured streaming, data lake on hadoop, etl monitoring, snowflake and bigquery datasets.", "Data Engineering"),
    ("Data engineering for analytics: airflow dags, spark clusters, dbt tests, warehouse snowflake schemas, kafka ingestion pipelines.", "Data Engineering"),
    ("Built a lakehouse: data lake ingestion, spark etl, kafka producers, air flow scheduling, snowflake data warehouse, bigquery marts.", "Data Engineering"),
    ("Hadoop to spark migration, etl re-architecture, airflow workflows, kafka topics, snowflake warehouse, bigquery export pipelines.", "Data Engineering"),
    # Mobile Development
    ("Android developer with Kotlin and Java. Published apps on Play Store, mobile UI, REST integration, android jetpack components.", "Mobile Development"),
    ("iOS engineer building Swift apps, xcode tooling, mobile performance, app store releases, ios design guidelines.", "Mobile Development"),
    ("Flutter developer: cross-platform mobile apps for android and ios, dart, mobile widgets, app store and play store publishing.", "Mobile Development"),
    ("React Native mobile developer shipping android ios apps, typescript, mobile navigation, push notifications, xcode and android studio.", "Mobile Development"),
    ("Kotlin android specialist: mobile architecture mvvm, kotlin coroutines, android sdk, play store deployments.", "Mobile Development"),
    ("Swift and SwiftUI mobile apps, ios frameworks, xcode debugging, mobile ux, app store optimization.", "Mobile Development"),
    ("Cross-platform mobile with flutter and react native, android kotlin ios swift bridges, mobile release pipelines.", "Mobile Development"),
    # QA / Testing
    ("QA engineer writing test cases and automation with Selenium and Cypress. Unit test coverage, quality assurance processes, pytest suites.", "QA / Testing"),
    ("Test automation lead: selenium webdriver, cypress e2e, unit test frameworks, qa strategy, pytest integration, testing metrics.", "QA / Testing"),
    ("Manual and automated testing, quality assurance, test cases design, selenium scripts, cypress regression packs, qa sign-off.", "QA / Testing"),
    ("SDET: built testing infrastructure with pytest, unit test mutation testing, selenium grids, cypress ci automation, qa tooling.", "QA / Testing"),
    ("Quality assurance engineer: test planning, automation with selenium and cypress, testing pyramid, unit test governance.", "QA / Testing"),
    ("Performance testing and qa automation, pytest fixtures, selenium page objects, test cases traceability, quality assurance audits.", "QA / Testing"),
    ("Cypress and selenium automation for web apps, unit test culture, testing documentation, qa release gates.", "QA / Testing"),
    # Cybersecurity
    ("Security analyst in SOC monitoring SIEM alerts, vulnerability scanning, firewall rules, incident response, infosec compliance audits.", "Cybersecurity"),
    ("Penetration testing web applications, vulnerability assessment, security hardening, encryption standards, soc workflows, compliance.", "Cybersecurity"),
    ("Infosec engineer: siem tuning, soc playbooks, penetration testing, firewall configuration, vulnerability management, security compliance.", "Cybersecurity"),
    ("Application security: encryption reviews, vulnerability triage, security code review, penetration tests, soc collaboration, compliance soc2.", "Cybersecurity"),
    ("SOC analyst tier 2: siem correlation rules, security incident response, firewall forensics, vulnerability disclosure, compliance checks.", "Cybersecurity"),
    ("Red team penetration testing, vulnerability exploitation labs, security awareness, encryption protocols, soc defense evasion testing.", "Cybersecurity"),
    ("Governance risk and compliance, security policies, vulnerability tracking, siem reporting, firewall audits, soc metrics.", "Cybersecurity"),
]

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
MODEL_PATH = os.path.join(MODEL_DIR, "role_classifier.joblib")


def main():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import Pipeline
    import joblib

    texts = [t for t, _ in DATA]
    labels = [r for _, r in DATA]

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True, ngram_range=(1, 2), min_df=1, sublinear_tf=True
        )),
        ("clf", LogisticRegression(max_iter=2000, C=4.0, random_state=42)),
    ])

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, texts, labels, cv=skf, scoring="f1_macro")
    print(f"5-fold CV macro-F1: {scores.mean():.3f} ± {scores.std():.3f}")

    pipeline.fit(texts, labels)
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump({
        "pipeline": pipeline,
        "labels": sorted(set(labels)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": len(DATA),
        "vectorizer": "tfidf(1,2) + logreg(C=4)",
        "cv_macro_f1": round(float(scores.mean()), 4),
    }, MODEL_PATH)
    print(f"saved -> {MODEL_PATH} ({os.path.getsize(MODEL_PATH)/1024:.0f} KB)")

    # sanity predictions
    for probe in [
        "kubernetes docker terraform ci/cd linux cloud devops aws",
        "react typescript css html ui ux frontend javascript",
        "spark airflow kafka snowflake etl pipelines warehouse",
    ]:
        pred = pipeline.predict([probe])[0]
        conf = float(max(pipeline.predict_proba([probe])[0]))
        print(f"  probe: {probe[:45]:<45} -> {pred} ({conf:.2f})")


if __name__ == "__main__":
    main()

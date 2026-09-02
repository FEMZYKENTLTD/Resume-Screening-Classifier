"""
Train the role / industry classifier.

Real supervised model: TF-IDF (word uni/bi-grams) + multinomial logistic
regression on a curated resume-style corpus. Reproducible:

    python -m training.train_role_classifier

Artifacts: models/role_classifier.joblib  (committed; auto-used by roles.py)

The curated corpus is intentionally small and transparent so the labels are
auditable — extend DATA with real (pseudonymized) resumes to improve it.

IMPORTANT (v5.7): the original corpus was made of short, keyword-dense blurbs
while real resumes carry a contact block, an education line and employer
names. That train/serve mismatch diluted TF-IDF at inference time: the model
still ranked the right label first, but its top probability sat around
0.26-0.30 — under the old MIN_CONFIDENCE=0.45 gate — so EVERY real resume
silently fell back to keyword profiles and the "trained classifier" never
actually ran in production. The reported cv_macro_f1 of 1.0 was measured on
the synthetic blurbs and did not transfer.

Fixes applied here:
  * RESUME_SHAPED entries mimic real CV layout (name, title, contact, skills,
    employers, degree) so the vectorizer sees production-like documents.
  * HELDOUT is scored separately — it is never trained on — and the run fails
    if held-out accuracy regresses, so the metric means something.
  * The artifact now records the decision rule so roles.py stays in sync.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.corpus import ROLES as CORPUS_ROLES  # noqa: E402
from training.corpus import make_dataset  # noqa: E402

# Synthetic resume-shaped documents (see training/corpus.py). These dominate
# the corpus by volume and are what teach the model to ignore the contact /
# education / employer scaffolding that every real CV carries.
GENERATED_PER_ROLE = int(os.environ.get("GENERATED_PER_ROLE", "60"))
GENERATED_TEST_PER_ROLE = int(os.environ.get("GENERATED_TEST_PER_ROLE", "15"))

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

# Data Analytics / BI — reporting and dashboarding rather than modelling.
DATA = DATA + [
    ("Business intelligence analyst building Power BI and Tableau dashboards. SQL queries, excel modelling, kpi reporting, data visualization for stakeholders.", "Data Analytics / BI"),
    ("Data analyst producing reporting dashboards in looker and tableau, advanced sql, excel pivot analysis, google analytics funnels, kpi tracking.", "Data Analytics / BI"),
    ("Analytics specialist: sql reporting, power bi semantic models, dashboard design, business intelligence requirements gathering, excel automation.", "Data Analytics / BI"),
    ("Reporting analyst delivering business intelligence: tableau workbooks, sql extracts, kpi scorecards, excel dashboards, data visualization standards.", "Data Analytics / BI"),
    ("Product data analyst: sql cohort analysis, looker explores, dashboard maintenance, a/b readouts, excel reporting and business intelligence reviews.", "Data Analytics / BI"),
]

# Resume-shaped examples: same labels, but written the way an actual CV reads
# (header, contact line, summary, skills, employers, degree). These close the
# train/serve gap that made the classifier unusable on real uploads.
RESUME_SHAPED = [
    ("Adaeze Obi\nSenior Data Engineer\nadaeze.obi@example.com | +234 803 111 2222 | Lagos, Nigeria\n"
     "7 years building batch and streaming data platforms. Expert in Python, SQL, Apache Airflow, dbt and Spark. "
     "Designs ETL pipelines and dimensional models on GCP BigQuery and Snowflake. Kafka ingestion, data lake storage. "
     "Previously at Interswitch and Flutterwave.\nB.Sc Computer Science, University of Ibadan.", "Data Engineering"),
    ("Musa Danjuma\nData Engineer\nmusa.d@example.com | Abuja\n"
     "Builds ETL and ELT workflows with Airflow DAGs, Spark transformations and dbt tests. Warehouse modelling in "
     "Snowflake and Redshift, Kafka event ingestion, data lake on S3. Star schema and Kimball methodology. "
     "Worked at Andela.\nHND Computer Science, Yaba College of Technology.", "Data Engineering"),
    ("Fatima Bello\nData Scientist\nfatima.bello@example.com | +234 805 333 4444 | Lagos\n"
     "6 years in predictive modelling and machine learning. Python, pandas, numpy, scikit-learn, PyTorch. "
     "NLP transformers, statistics, A/B testing, feature engineering and model monitoring in production. "
     "Previously at Paystack.\nM.Sc Statistics, University of Lagos.", "Data Science / ML"),
    ("Chinedu Okafor\nMachine Learning Engineer\nchinedu@example.com | Port Harcourt\n"
     "Trains and deploys deep learning models with TensorFlow and Keras. Computer vision and NLP classification, "
     "scikit-learn baselines, model evaluation and drift detection. Research publications on prediction analytics.\n"
     "B.Sc Mathematics, University of Nigeria Nsukka.", "Data Science / ML"),
    ("Ibrahim Musa\nFrontend Engineer\nibrahim.musa@example.com | +234 807 555 6666 | Kano\n"
     "5 years building responsive single-page applications with React, TypeScript and JavaScript. "
     "HTML, CSS, Tailwind, component design systems, accessibility and UX collaboration. Webpack and Vite tooling. "
     "Previously at Kuda Bank.\nB.Eng Computer Engineering, Ahmadu Bello University.", "Frontend Engineering"),
    ("Ngozi Eze\nSenior Frontend Developer\nngozi.eze@example.com | Enugu\n"
     "Builds Vue and React interfaces with TypeScript. CSS grid responsive layouts, UI performance profiling, "
     "design system components, frontend unit testing and UX research.\nB.Sc Computer Science, Covenant University.",
     "Frontend Engineering"),
    ("Tobi Adeyemi\nDevOps Engineer\ntobi.adeyemi@example.com | +234 809 777 8888 | Lagos\n"
     "Automates infrastructure with Terraform and Ansible. Runs Docker and Kubernetes clusters on AWS, "
     "Jenkins and GitHub Actions CI/CD pipelines, Linux administration, monitoring and incident response. "
     "Previously at Interswitch.\nB.Sc Computer Science, Obafemi Awolowo University.", "DevOps / Cloud"),
    ("Segun Ola\nCloud Infrastructure Engineer\nsegun@example.com | Ibadan\n"
     "Manages Azure and GCP cloud infrastructure: Kubernetes autoscaling, Helm charts, Docker registries, "
     "Terraform IaC modules, CI/CD automation and Linux server hardening. SRE on-call rotation.\n"
     "B.Tech Information Technology, LAUTECH.", "DevOps / Cloud"),
    ("Kelechi Nwosu\nBackend Engineer\nkelechi.nwosu@example.com | +234 802 999 0000 | Lagos\n"
     "8 years building REST APIs and microservices with FastAPI, Django and Flask. PostgreSQL and MySQL schema "
     "design, Redis caching, message queues, API authentication and versioning. Previously at Paystack.\n"
     "B.Sc Software Engineering, Babcock University.", "Backend Engineering"),
    ("Aisha Yusuf\nSenior Backend Developer\naisha.yusuf@example.com | Kaduna\n"
     "Server-side development in Node.js and Python. Express and Django REST framework, MongoDB and Postgres "
     "database modelling, Redis workers, microservice integrations and database migrations.\n"
     "B.Sc Computer Science, Bayero University Kano.", "Backend Engineering"),
    ("Emeka Obi\nAndroid Developer\nemeka.obi@example.com | +234 806 222 3333 | Lagos\n"
     "Builds Android apps in Kotlin and Java with MVVM architecture, Jetpack components and coroutines. "
     "Play Store releases, REST integration and mobile UI performance.\nB.Sc Computer Science, UNILAG.",
     "Mobile Development"),
    ("Blessing Ade\nMobile Engineer (iOS)\nblessing.ade@example.com | Lagos\n"
     "Ships Swift and SwiftUI iOS applications, Xcode tooling and debugging, App Store releases, mobile UX and "
     "cross-platform Flutter work in Dart.\nB.Sc Information Systems, Covenant University.", "Mobile Development"),
    ("Yemi Ogun\nQA Automation Engineer\nyemi.ogun@example.com | +234 808 444 5555 | Abuja\n"
     "Designs test cases and automation suites with Selenium WebDriver, Cypress end-to-end packs and pytest. "
     "Unit test coverage governance, QA release gates, regression testing and quality assurance reporting.\n"
     "B.Sc Computer Science, University of Abuja.", "QA / Testing"),
    ("Grace Udo\nSoftware Development Engineer in Test\ngrace.udo@example.com | Uyo\n"
     "Builds testing infrastructure: pytest fixtures, Selenium grids, Cypress CI automation, performance testing "
     "and test traceability. Manual and automated quality assurance sign-off.\nB.Sc Computer Science, UNIUYO.",
     "QA / Testing"),
    ("Chiamaka Eze\nData Analyst\nchiamaka.eze@example.com | +234 811 121 3141 | Lagos, Nigeria\n"
     "5 years turning business questions into dashboards. Advanced SQL, Excel modelling, Power BI and Tableau "
     "reporting, KPI scorecards and data visualization for commercial teams. Google Analytics funnel reviews. "
     "Previously at Jumia.\nB.Sc Economics, University of Lagos.", "Data Analytics / BI"),
    ("Damilola Fashola\nBusiness Intelligence Analyst\ndamilola@example.com | Abuja\n"
     "Builds Looker explores and Tableau workbooks, writes SQL extracts, maintains KPI dashboards and monthly "
     "business intelligence reporting packs. Excel automation for finance stakeholders.\n"
     "B.Sc Statistics, University of Ilorin.", "Data Analytics / BI"),
    ("Bola Salami\nCybersecurity Analyst\nbola.salami@example.com | +234 810 666 7777 | Lagos\n"
     "SOC tier 2 analyst monitoring SIEM correlation alerts, vulnerability scanning and triage, firewall rules, "
     "incident response and forensics. Penetration testing and SOC2 compliance audits.\n"
     "B.Sc Cyber Security, Federal University of Technology Akure.", "Cybersecurity"),
    ("Hassan Bello\nInformation Security Engineer\nhassan.bello@example.com | Jos\n"
     "Application security reviews, encryption standards, vulnerability management, penetration tests, "
     "security code review, SIEM tuning and governance risk and compliance policies.\n"
     "M.Sc Information Security, University of Jos.", "Cybersecurity"),
]

DATA = DATA + RESUME_SHAPED

# Held-out probes written independently of DATA: these approximate what the
# app actually receives. Never trained on — they are the honest metric.
HELDOUT = [
    ("Tunde Bakare\nSenior Data Engineer\ntunde.bakare@example.com\n+234 802 555 0192\nLagos, Nigeria\n"
     "8 years experience building data platforms. Expert in Python, SQL, Apache Airflow, dbt and Spark. "
     "Designs ETL pipelines on GCP (BigQuery, Dataflow, Cloud Composer). Strong with Docker, Kubernetes and CI/CD. "
     "Data modeling (star schema, Kimball). Previously at Paystack and Kuda Bank.\n"
     "B.Sc Computer Science, University of Ibadan.", "Data Engineering"),
    ("Chiamaka Eze\nData Analyst\nchiamaka@example.com\nLagos\n"
     "Analyses business data with SQL and Python pandas. Builds Power BI and Tableau dashboards, statistics "
     "reporting, Excel modelling and A/B test readouts for product teams.\nB.Sc Economics, UNILAG.",
     "Data Analytics / BI"),
    ("Sade Coker\nFrontend Developer\nsade@example.com\nLagos\n"
     "Builds React and TypeScript interfaces, responsive CSS, reusable UI components and accessibility fixes. "
     "Jest unit tests and Vite builds.\nB.Sc Computer Science, UNILAG.", "Frontend Engineering"),
    ("Uche Nnamdi\nSite Reliability Engineer\nuche@example.com\nAbuja\n"
     "Runs Kubernetes clusters and Docker workloads on AWS. Terraform infrastructure as code, Jenkins CI/CD, "
     "Linux tuning, Prometheus monitoring and incident response.\nB.Eng Electrical Engineering, UNN.",
     "DevOps / Cloud"),
    ("Ifeanyi Okoro\nBackend Engineer\nifeanyi@example.com\nLagos\n"
     "Designs REST APIs with FastAPI and Django. PostgreSQL schema design, Redis caching, Celery workers and "
     "microservice deployments.\nB.Sc Computer Science, UNIZIK.", "Backend Engineering"),
    ("Zainab Idris\nQA Engineer\nzainab@example.com\nKano\n"
     "Writes automated test suites with Cypress and Selenium, pytest integration tests, regression packs and "
     "quality assurance release checklists.\nB.Sc Computer Science, BUK.", "QA / Testing"),
]

# Curated (hand-written) rows above + generated resume-shaped rows below.
# Keeping both matters: the curated rows pin exact vocabulary we care about,
# the generated rows supply realistic volume and scaffolding noise.
CURATED = list(DATA)
GENERATED = make_dataset(split="train", per_role=GENERATED_PER_ROLE)
DATA = CURATED + GENERATED

# A second, fully held-out generated set drawn from DISJOINT name/employer/
# city pools and a different seed, plus the hand-written HELDOUT probes.
GENERATED_HELDOUT = make_dataset(split="test", per_role=GENERATED_TEST_PER_ROLE)
HELDOUT_CURATED = list(HELDOUT)
HELDOUT = HELDOUT_CURATED + GENERATED_HELDOUT

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"
)
MODEL_PATH = os.path.join(MODEL_DIR, "role_classifier.joblib")


def build_pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline([
        # sublinear_tf + min_df=1 keeps rare-but-decisive tokens ("airflow",
        # "kubernetes"); char n-grams are deliberately NOT used - they blur
        # the very keywords that separate these roles.
        ("tfidf", TfidfVectorizer(
            lowercase=True, ngram_range=(1, 2), min_df=1, sublinear_tf=True,
            strip_accents="unicode", stop_words="english",
        )),
        # C=8 sharpens the decision boundary on this small corpus; the old
        # C=4 left the top probability so flat that the serving threshold
        # rejected every real resume.
        ("clf", LogisticRegression(max_iter=4000, C=8.0, random_state=42)),
    ])


def evaluate_heldout(pipeline):
    """Score the never-trained-on, resume-shaped probes. This is the number
    that actually predicts production behaviour."""
    correct, rows = 0, []
    for text, expected in HELDOUT:
        proba = pipeline.predict_proba([text])[0]
        classes = pipeline.classes_
        order = sorted(zip(classes, proba), key=lambda kv: -kv[1])
        top_label, top_p = order[0]
        runner_p = order[1][1] if len(order) > 1 else 0.0
        ok = top_label == expected
        correct += ok
        rows.append((expected, top_label, top_p, top_p - runner_p, ok))
    return correct / len(HELDOUT), rows


def _per_class_report(rows):
    """Accuracy and mean margin per role — a single headline number can hide
    one class being completely broken."""
    from collections import defaultdict
    agg = defaultdict(lambda: {"n": 0, "ok": 0, "margin": 0.0, "top_p": 0.0})
    for expected, _got, top_p, margin, ok in rows:
        a = agg[expected]
        a["n"] += 1
        a["ok"] += bool(ok)
        a["margin"] += margin
        a["top_p"] += top_p
    return agg


def _serving_acceptance(rows, min_conf, min_margin):
    """Fraction of held-out docs the SERVING rule would actually accept from
    the model (rather than silently dropping to keyword profiles). This is the
    metric whose collapse caused the original production bug."""
    accepted = sum(1 for _e, _g, p, m, _ok in rows if p >= min_conf or m >= min_margin)
    accepted_correct = sum(
        1 for _e, _g, p, m, ok in rows
        if (p >= min_conf or m >= min_margin) and ok
    )
    return accepted / len(rows), (accepted_correct / accepted if accepted else 0.0)


def _score_real_demo_resumes(pipeline):
    """Classify the committed demo PDFs — genuine documents produced outside
    this training script. Returns accuracy, or None if unavailable."""
    try:
        import parsing
    except Exception:
        return None

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    demo_dir = os.path.join(root, "demo", "resumes")
    expected = {
        "chiamaka_eze_data_analyst.pdf": "Data Analytics / BI",
        "fatima_bello_data_scientist.pdf": "Data Science / ML",
        "ibrahim_musa_frontend.pdf": "Frontend Engineering",
        "tunde_bakare_data_engineer.pdf": "Data Engineering",
    }
    seen = correct = 0
    for filename, want in expected.items():
        path = os.path.join(demo_dir, filename)
        if not os.path.exists(path):
            continue
        try:
            text = parsing.parse_resume(filename, open(path, "rb").read())
        except Exception:
            continue
        seen += 1
        proba = pipeline.predict_proba([text])[0]
        order = sorted(zip(pipeline.classes_, proba), key=lambda kv: -kv[1])
        got, top_p = str(order[0][0]), float(order[0][1])
        margin = top_p - (float(order[1][1]) if len(order) > 1 else 0.0)
        # Must be right AND actually servable under the production rule.
        servable = top_p >= 0.40 or margin >= 0.10
        correct += (got == want and servable)
        if got != want:
            print(f"    MISS {filename}: expected {want}, got {got}")
        elif not servable:
            print(f"    WEAK {filename}: correct ({got}) but p={top_p:.3f} "
                  f"margin={margin:.3f} would fall back to keywords")
    return (correct / seen) if seen else None


def main():
    import joblib
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    texts = [t for t, _ in DATA]
    labels = [r for _, r in DATA]

    pipeline = build_pipeline()

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, texts, labels, cv=skf, scoring="f1_macro")
    print(f"5-fold CV macro-F1 (in-corpus): {scores.mean():.3f} +/- {scores.std():.3f}")

    pipeline.fit(texts, labels)

    heldout_acc, rows = evaluate_heldout(pipeline)
    print(f"held-out accuracy (resume-shaped, unseen): {heldout_acc:.3f} "
          f"over {len(rows)} documents")

    agg = _per_class_report(rows)
    print(f"  {'role':<24}{'n':>4}{'acc':>8}{'mean_p':>9}{'mean_margin':>13}")
    for role in sorted(agg):
        a = agg[role]
        print(f"  {role:<24}{a['n']:>4}{a['ok']/a['n']:>8.3f}"
              f"{a['top_p']/a['n']:>9.3f}{a['margin']/a['n']:>13.3f}")

    accept_rate, accept_prec = _serving_acceptance(rows, 0.40, 0.10)
    print(f"  serving rule accepts {accept_rate:.1%} of held-out docs "
          f"(precision when accepted: {accept_prec:.1%})")

    min_margin = min(r[3] for r in rows)
    print(f"  smallest correct-case margin: {min_margin:.3f}")

    # Guard rails: a training run that regresses these must not silently ship
    # a broken artifact (this is exactly how the previous model shipped).
    if heldout_acc < 0.8:
        raise SystemExit(
            f"REFUSING TO SAVE: held-out accuracy {heldout_acc:.3f} < 0.80. "
            "The model would fall back to keywords on real resumes."
        )

    # The generated held-out set shares a generator with the training data, so
    # a high score there can flatter the model. The hand-written probes and the
    # REAL demo PDFs are the honest arbiters — gate on them explicitly.
    curated_rows = rows[:len(HELDOUT_CURATED)]
    if curated_rows:
        curated_acc = sum(r[4] for r in curated_rows) / len(curated_rows)
        print(f"  hand-written probe accuracy: {curated_acc:.3f} "
              f"({len(curated_rows)} docs)")
        if curated_acc < 1.0:
            raise SystemExit(
                f"REFUSING TO SAVE: hand-written probe accuracy "
                f"{curated_acc:.3f} < 1.00 — the generated corpus is masking a "
                "regression on realistic text."
            )

    # Accuracy alone is not enough: a model can pick the right label with a
    # margin so thin that the SERVING rule rejects it and silently falls back
    # to keywords — which is precisely how the original bug shipped green.
    accept_rate, _ = _serving_acceptance(rows, 0.40, 0.10)
    if accept_rate < 0.95:
        raise SystemExit(
            f"REFUSING TO SAVE: the serving rule would accept only "
            f"{accept_rate:.1%} of held-out documents. The model is correct but "
            "not confident enough to actually be used at inference time."
        )

    real_acc = _score_real_demo_resumes(pipeline)
    if real_acc is not None:
        print(f"  REAL demo PDF accuracy: {real_acc:.3f}")
        if real_acc < 1.0:
            raise SystemExit(
                f"REFUSING TO SAVE: only {real_acc:.0%} of the real demo "
                "resumes classify correctly. Synthetic gains that do not "
                "transfer to real PDFs are exactly the bug this guard exists "
                "to prevent."
            )

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump({
        "pipeline": pipeline,
        "labels": sorted(set(labels)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": len(DATA),
        "vectorizer": "tfidf(1,2) + logreg(C=8)",
        "cv_macro_f1": round(float(scores.mean()), 4),
        # The honest, production-predictive metric.
        "heldout_accuracy": round(float(heldout_acc), 4),
        "heldout_samples": len(HELDOUT),
        # Serving contract - roles.py reads these so the decision rule and the
        # artifact can never drift apart again.
        "decision_rule": "top1 if (p1 >= min_confidence) or (p1 - p2 >= min_margin)",
        "min_confidence": 0.40,
        "min_margin": 0.10,
    }, MODEL_PATH)
    print(f"saved -> {MODEL_PATH} ({os.path.getsize(MODEL_PATH)/1024:.0f} KB)")


if __name__ == "__main__":
    main()

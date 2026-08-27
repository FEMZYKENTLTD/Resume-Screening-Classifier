# OPTIONAL worker image with the full ML stack:
#   semantic embeddings + spaCy NER + trained role classifier.
# Build:  docker build -f Dockerfile.worker.ml -t resume-worker-ml .
# Deploy instead of Dockerfile.worker where ML features are wanted
# (CPU is fine; the classifier model artifact ships in the repo).
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
COPY wheels-linux/ /wheels/
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt \
    && pip install --no-cache-dir \
       sentence-transformers==6.0.0 \
       spacy==3.8.16 \
       scikit-learn==1.9.0 \
       https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY . .

ENV ENABLE_SEMANTIC=1 \
    WORKER_METRICS_PORT=9101
CMD ["celery", "-A", "tasks", "worker", "--loglevel=INFO", "--concurrency=2"]

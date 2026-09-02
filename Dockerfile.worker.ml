# OPTIONAL worker image with the full ML stack:
#   semantic embeddings + spaCy NER + trained role classifier.
# Build:  docker build -f Dockerfile.worker.ml -t resume-worker-ml .
# NOTE: no wheels-linux/ COPY — that mirror is git-ignored and breaks
# remote builds (Fly/GitHub/Render).
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       sentence-transformers==6.0.0 \
       spacy==3.8.16 \
       scikit-learn==1.9.0

# See Dockerfile.api: the NER model install is resilient to the GitHub
# release-asset CDN being blocked, and degrades instead of failing the build.
# Set --build-arg SPACY_MODEL_REQUIRED=1 to hard-fail the build instead of
# shipping without NER.
ARG SPACY_MODEL_REQUIRED=0
COPY scripts/install_spacy_model.sh /tmp/install_spacy_model.sh
RUN chmod +x /tmp/install_spacy_model.sh \
    && SPACY_MODEL_REQUIRED="$SPACY_MODEL_REQUIRED" /tmp/install_spacy_model.sh

COPY . .

ENV ENABLE_SEMANTIC=1 \
    WORKER_METRICS_PORT=9101
CMD ["celery", "-A", "tasks", "worker", "--loglevel=INFO", "--concurrency=2"]
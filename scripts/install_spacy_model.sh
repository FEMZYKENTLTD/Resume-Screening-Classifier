#!/bin/sh
# Install the spaCy NER model (en_core_web_sm) resiliently.
#
# WHY THIS EXISTS
# ---------------
# The Dockerfiles used to pin the model as a raw GitHub release URL:
#
#   pip install https://github.com/explosion/spacy-models/releases/download/...
#
# GitHub serves release assets from a *separate* CDN host
# (release-assets.githubusercontent.com / objects.githubusercontent.com).
# Corporate proxies, CI egress allowlists and sandboxed builders routinely
# permit github.com but block that CDN — and because the URL sat in the same
# `RUN pip install` layer as everything else, a CDN hiccup failed the ENTIRE
# image build. NER is documented as an OPTIONAL extra with a regex fallback,
# so it must never be able to take the deployment down.
#
# Strategy, in order:
#   1. `spacy download` — resolves the correct model build for the installed
#      spaCy version instead of hardcoding one (no more version drift).
#   2. the pinned release URL — the original path, kept as a fallback.
#   3. give up LOUDLY but with exit 0 — the app degrades to regex extraction,
#      exactly as documented.
#
# Set SPACY_MODEL_REQUIRED=1 to make failure fatal (useful if you want a build
# to hard-fail rather than silently ship without NER).

set -e

MODEL="${SPACY_MODEL:-en_core_web_sm}"
MODEL_VERSION="${SPACY_MODEL_VERSION:-3.8.0}"
FALLBACK_URL="https://github.com/explosion/spacy-models/releases/download/${MODEL}-${MODEL_VERSION}/${MODEL}-${MODEL_VERSION}-py3-none-any.whl"

echo "→ installing spaCy model '${MODEL}'"

if python -m spacy download "${MODEL}" 2>/dev/null; then
    echo "✅ installed '${MODEL}' via 'spacy download'"
elif pip install --no-cache-dir "${FALLBACK_URL}" 2>/dev/null; then
    echo "✅ installed '${MODEL}' via the pinned release URL"
else
    echo "⚠️  Could not install '${MODEL}'."
    echo "    GitHub's release-asset CDN is likely blocked by this network."
    if [ "${SPACY_MODEL_REQUIRED}" = "1" ]; then
        echo "❌ SPACY_MODEL_REQUIRED=1 — failing the build."
        exit 1
    fi
    echo "    Continuing: NER degrades to the documented regex extractors."
    echo "    extracted_fields.extraction_method will report 'regex-heuristic'."
    exit 0
fi

# Verify the model actually loads — a partially-installed wheel is worse than
# a missing one, because ner_available() would claim NER works.
python - <<'PY' || echo "⚠️  model installed but failed to load; regex fallback will be used"
import sys
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    doc = nlp("Tunde Bakare worked at Paystack in Lagos.")
    print("✅ model loads; sample entities:", [(e.text, e.label_) for e in doc.ents])
except Exception as exc:
    print(f"load check failed: {type(exc).__name__}: {exc}")
    sys.exit(1)
PY

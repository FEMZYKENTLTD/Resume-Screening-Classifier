"""
True NER extraction via spaCy (en_core_web_sm), with graceful degradation.

When spaCy + the model are installed, name/organization extraction uses
real NER (PERSON/ORG entities). When they're not, extractors.py falls back
to the documented regex heuristics — zero hard dependency for the base
pipeline. Enable with:

    pip install spacy
    pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
"""

_NLP = None
_NLP_TRIED = False


def ner_available() -> bool:
    """True if spaCy and en_core_web_sm load successfully (cached)."""
    global _NLP, _NLP_TRIED
    if _NLP_TRIED:
        return _NLP is not None
    _NLP_TRIED = True
    try:
        import spacy
        _NLP = spacy.load("en_core_web_sm")
    except Exception:                          # pragma: no cover
        _NLP = None
    return _NLP is not None


def extract_name_ner(text: str):
    """First PERSON entity, sanity-filtered to plausible person names."""
    if not ner_available():
        return None
    doc = _NLP((text or "")[:8000])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            words = name.split()
            if 1 <= len(words) <= 4 and len(name) <= 60 and not any(
                ch.isdigit() for ch in name
            ):
                return name
    return None


def extract_organizations(text: str, cap: int = 5):
    """Distinct ORG entities (employers / institutions), order-preserved."""
    if not ner_available():
        return []
    doc = _NLP((text or "")[:8000])
    seen, orgs = set(), []
    for ent in doc.ents:
        if ent.label_ == "ORG":
            name = ent.text.strip()
            if name.lower() not in seen and 2 <= len(name) <= 60:
                seen.add(name.lower())
                orgs.append(name)
                if len(orgs) >= cap:
                    break
    return orgs

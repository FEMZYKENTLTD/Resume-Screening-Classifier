"""
Pseudonymize real resumes so they can be used as training data.

WHY
---
Real resumes are the single highest-value input for the role classifier, but
they are also personal data. A CV contains a full name, personal email,
phone number, home address, and often a date of birth or a national ID. That
must never be committed to a public repository, and under NDPR (Nigeria) /
GDPR it must not be retained without a lawful basis.

This module removes direct identifiers while PRESERVING the signal the
classifier actually learns from: job titles, skills, technologies, seniority
and the overall document shape.

WHAT IS REMOVED / REPLACED
--------------------------
  emails, phone numbers, URLs, LinkedIn/GitHub handles, street addresses,
  national ID / BVN-style long digit runs, and the candidate name (replaced
  with a stable pseudonym so the document still "reads" like a resume).

WHAT IS DELIBERATELY KEPT
-------------------------
  job titles, skills and tools, employer names (they are public companies,
  not personal data, and they carry genuine domain signal), city, degree and
  institution, years of experience.

  If your policy requires employer removal too, pass drop_employers=True.

Pseudonymization is deterministic: the same input name always maps to the
same pseudonym, so a person appearing in two documents stays consistent
without the real name ever being stored.

Usage:
    from training.pseudonymize import pseudonymize
    safe_text, report = pseudonymize(raw_resume_text)
"""

from __future__ import annotations

import hashlib
import re

# Deterministic pseudonym pools (not tied to any real person).
_PSEUDO_FIRST = [
    "Ada", "Bode", "Chika", "Dami", "Ebun", "Femi", "Gozie", "Hauwa",
    "Ify", "Jide", "Kemi", "Lanre", "Maryam", "Nkem", "Obi", "Peju",
    "Rita", "Sade", "Tayo", "Uche", "Vera", "Wale", "Yemi", "Zara",
]
_PSEUDO_LAST = [
    "Adebayo", "Balogun", "Chukwu", "Danladi", "Eze", "Falade", "Garba",
    "Hassan", "Ibrahim", "Jimoh", "Kalu", "Lawal", "Mustapha", "Nwachukwu",
    "Okonkwo", "Popoola", "Quadri", "Rufai", "Sani", "Tijani",
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
HANDLE_RE = re.compile(
    r"\b(?:linkedin\.com/in/|github\.com/|twitter\.com/|x\.com/)[\w.-]+",
    re.IGNORECASE,
)
# Phone numbers: international or local, tolerant of spaces/dashes/parens.
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
# Long digit runs = national ID, BVN, passport, account numbers.
LONGNUM_RE = re.compile(r"\b\d{9,}\b")
# Street addresses (number + street-ish word).
ADDRESS_RE = re.compile(
    r"\b(?:(?:flat|apt|apartment|suite|no\.?)\s*[\w-]+,?\s*)?"
    r"\d{1,4}[A-Za-z]?,?\s+(?:[A-Z][\w.-]*\s+){1,3}"
    r"(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?|Close|Crescent|Drive|Lane|Way|Estate|Boulevard|Blvd\.?)\b",
    re.IGNORECASE,
)
# Employment-date ranges: two 4-digit years, optionally separated by any dash.
_DATE_RANGE_RE = re.compile(
    r"(?:19|20)\d{2}\s*[-–—/]\s*(?:(?:19|20)\d{2}|present|date|now)?",
    re.IGNORECASE,
)
DOB_RE = re.compile(
    r"\b(?:date of birth|d\.o\.b\.?|dob)\s*[:\-]?\s*[\w/,. -]{6,20}",
    re.IGNORECASE,
)

_NAME_LINE_BLOCKLIST = (
    "resume", "curriculum", "vitae", "cv", "profile", "summary", "objective",
    "contact", "experience", "education", "skills", "projects",
)


def _is_phone(raw: str) -> bool:
    """True if `raw` is plausibly a phone number rather than a date range.

    Shared by the scrubber and the auditor so they can never disagree — an
    auditor stricter than the scrubber rejects every document forever.
    """
    raw = raw.strip()
    if _DATE_RANGE_RE.fullmatch(raw):
        return False
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        return False
    # Two 4-digit years glued together by a dash ("2018-2021") look like a
    # 8-digit "number" but are employment dates.
    if re.fullmatch(r"(?:19|20)\d{2}\s*[-–—/]\s*(?:19|20)\d{2}", raw):
        return False
    return True


def _stable_pseudonym(real: str) -> str:
    """Same input -> same pseudonym, without storing the real value."""
    digest = hashlib.sha256(real.strip().lower().encode("utf-8")).digest()
    first = _PSEUDO_FIRST[digest[0] % len(_PSEUDO_FIRST)]
    last = _PSEUDO_LAST[digest[1] % len(_PSEUDO_LAST)]
    return f"{first} {last}"


def _looks_like_name(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 45:
        return False
    low = line.lower()
    if any(k in low for k in _NAME_LINE_BLOCKLIST):
        return False
    if "@" in line or any(ch.isdigit() for ch in line):
        return False
    words = line.split()
    if not 2 <= len(words) <= 4:
        return False
    return all(w[:1].isupper() for w in words if w[:1].isalpha())


def pseudonymize(text: str, drop_employers: bool = False,
                 employers: list[str] | None = None):
    """Return (pseudonymized_text, report).

    `report` counts what was removed, so an operator can audit the scrub
    before any document is committed.
    """
    if not text:
        return "", {"name": 0, "email": 0, "phone": 0, "url": 0,
                    "address": 0, "id_number": 0, "dob": 0}

    report = {"name": 0, "email": 0, "phone": 0, "url": 0,
              "address": 0, "id_number": 0, "dob": 0}

    # Order matters: strip DOB/addresses/IDs before the generic phone regex,
    # which would otherwise swallow parts of them.
    text, n = DOB_RE.subn("Date of birth: [REDACTED]", text)
    report["dob"] = n
    text, n = ADDRESS_RE.subn("[ADDRESS]", text)
    report["address"] = n
    text, n = LONGNUM_RE.subn("[ID]", text)
    report["id_number"] = n
    text, n = HANDLE_RE.subn("[PROFILE]", text)
    report["url"] += n
    text, n = URL_RE.subn("[URL]", text)
    report["url"] += n
    text, n = EMAIL_RE.subn("candidate@example.com", text)
    report["email"] = n

    def _phone_sub(m):
        raw = m.group(0)
        # "2018 - 2021", "2019 – Present", "Mar 2022 - date" are employment
        # dates, not phone numbers. The naive length check destroyed them,
        # which wrecked the employment-history signal the classifier uses.
        if not _is_phone(raw):
            return raw
        report["phone"] += 1
        return "+234 800 000 0000"

    text = PHONE_RE.sub(_phone_sub, text)

    # Replace the candidate name on the first few lines (resume header).
    lines = text.splitlines()
    for i, line in enumerate(lines[:6]):
        if _looks_like_name(line):
            pseudo = _stable_pseudonym(line)
            real_words = [w.strip(".,") for w in line.split()]
            lines[i] = pseudo
            # Scrub later mentions of the same person (headers/footers).
            for j in range(len(lines)):
                for w in real_words:
                    if len(w) > 2:
                        lines[j] = re.sub(rf"\b{re.escape(w)}\b", "", lines[j])
            report["name"] += 1
            break
    text = "\n".join(lines)

    if drop_employers and employers:
        for emp in employers:
            text = re.sub(rf"\b{re.escape(emp)}\b", "[EMPLOYER]", text,
                          flags=re.IGNORECASE)

    # Tidy whitespace left behind by removals.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), report


def contains_pii(text: str) -> list[str]:
    """Audit helper: which direct identifiers are still present?

    Used as a safety gate before anything is written to the repo.
    """
    found = []
    if EMAIL_RE.search(text or ""):
        # the placeholder is allowed
        leftovers = [e for e in EMAIL_RE.findall(text)
                     if e != "candidate@example.com"]
        if leftovers:
            found.append("email")
    if LONGNUM_RE.search(text or ""):
        found.append("id_number")
    if HANDLE_RE.search(text or "") or URL_RE.search(text or ""):
        found.append("url")
    for m in PHONE_RE.finditer(text or ""):
        if m.group(0).strip() == "+234 800 000 0000":
            continue
        if _is_phone(m.group(0)):
            found.append("phone")
            break
    return sorted(set(found))

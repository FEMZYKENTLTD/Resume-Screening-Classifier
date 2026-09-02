"""
Ingest REAL resumes into the training corpus — safely.

This is the highest-value improvement available to the role classifier:
synthetic data can only teach document *shape*, real CVs teach the messy
vocabulary people actually use ("Snowflake/Redshift", "MS Excel (advanced)",
"Airflow 2.x", typos, inconsistent casing, tables flattened by the parser).

The pipeline refuses to produce unsafe output:

    PDF/DOCX  ->  parse  ->  pseudonymize  ->  PII audit  ->  JSONL

Any document that still contains a direct identifier after scrubbing is
REJECTED, not silently written. The JSONL it produces contains no names,
emails, phone numbers, URLs or ID numbers.

USAGE
-----
1. Drop real resumes into a folder, one sub-folder per role label:

       real_resumes/
         Data Engineering/        alice_cv.pdf  bob_cv.docx
         Frontend Engineering/    ...
         Data Analytics - BI/     ...

   (Folder names map to labels; " - " becomes " / " so you can express
   "Data Analytics / BI" on filesystems that dislike slashes.)

2. Run:

       python -m training.ingest_real_resumes real_resumes/ \
           --out training/real_corpus.jsonl

3. Review the audit summary, then retrain:

       python -m training.train_role_classifier

`training/real_corpus.jsonl` is picked up AUTOMATICALLY by the trainer when
present. It is git-ignored by default — decide deliberately whether your
pseudonymized corpus may be committed.

IMPORTANT: pseudonymization reduces risk, it does not grant permission.
Only ingest resumes you have a lawful basis to process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parsing  # noqa: E402
from training.pseudonymize import contains_pii, pseudonymize  # noqa: E402

# Minimum characters for a document to be worth training on.
MIN_CHARS = 200


def label_from_dirname(name: str) -> str:
    """'Data Analytics - BI' -> 'Data Analytics / BI'."""
    return name.replace(" - ", " / ").strip()


def ingest(src_dir: str, out_path: str, drop_employers: bool = False,
           min_chars: int = MIN_CHARS) -> dict:
    rows, stats = [], {
        "seen": 0, "ok": 0, "skipped_short": 0,
        "skipped_unreadable": 0, "rejected_pii": 0, "labels": {},
    }

    for entry in sorted(os.listdir(src_dir)):
        role_dir = os.path.join(src_dir, entry)
        if not os.path.isdir(role_dir):
            continue
        label = label_from_dirname(entry)

        for filename in sorted(os.listdir(role_dir)):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in parsing.SUPPORTED_EXTENSIONS:
                continue
            stats["seen"] += 1
            path = os.path.join(role_dir, filename)

            try:
                raw = parsing.parse_resume(filename, open(path, "rb").read())
            except Exception as exc:
                print(f"  ! unreadable {filename}: {exc}")
                stats["skipped_unreadable"] += 1
                continue

            safe, report = pseudonymize(raw, drop_employers=drop_employers)

            if len(safe) < min_chars:
                print(f"  - too short after scrub ({len(safe)} chars): {filename}")
                stats["skipped_short"] += 1
                continue

            leftover = contains_pii(safe)
            if leftover:
                # Fail closed. Never write a document we could not fully scrub.
                print(f"  ✗ REJECTED {filename}: still contains {leftover}")
                stats["rejected_pii"] += 1
                continue

            rows.append({"text": safe, "label": label, "redacted": report})
            stats["ok"] += 1
            stats["labels"][label] = stats["labels"].get(label, 0) + 1

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="folder of resumes, one sub-folder per role")
    ap.add_argument("--out", default="training/real_corpus.jsonl")
    ap.add_argument("--drop-employers", action="store_true",
                    help="also redact employer names")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        raise SystemExit(f"not a directory: {args.src}")

    print(f"→ ingesting from {args.src}")
    stats = ingest(args.src, args.out, args.drop_employers, args.min_chars)

    print("\n=== ingestion summary ===")
    print(f"  files seen        : {stats['seen']}")
    print(f"  ingested          : {stats['ok']}")
    print(f"  skipped (short)   : {stats['skipped_short']}")
    print(f"  skipped (unread)  : {stats['skipped_unreadable']}")
    print(f"  REJECTED (PII)    : {stats['rejected_pii']}")
    for label, n in sorted(stats["labels"].items()):
        print(f"    {label:<26}{n}")
    print(f"\n  wrote -> {args.out}")

    if stats["rejected_pii"]:
        print("\n  ⚠️  Some documents could not be fully scrubbed and were "
              "NOT written. Inspect them manually before retrying.")
    if stats["ok"]:
        print("\n  Next: python -m training.train_role_classifier")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Grant / revoke admin rights and force-logout accounts, straight against the DB.

The API can do this too (`POST /admin/users/{id}/admin`), but that needs an
existing admin. This script is the break-glass path for an instance whose
admin flag was lost — point it at the same DATABASE_URL the API uses.

Usage
-----
    export DATABASE_URL=postgresql://...        # same URL as the API
    python scripts/grant_admin.py --list
    python scripts/grant_admin.py --username femzyk
    python scripts/grant_admin.py --email me@example.com
    python scripts/grant_admin.py --username someone --revoke
    python scripts/grant_admin.py --username femzyk --logout   # kill sessions

Notes
-----
* Matching is case-insensitive.
* `--logout` bumps users.token_version, which instantly invalidates every
  session token already issued for that account (any device).
* Nothing here bypasses password auth: it only flips role/session columns.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func                     # noqa: E402

from database import DATABASE_URL, SessionLocal  # noqa: E402
from models import User                          # noqa: E402


def _print_users(db) -> None:
    users = db.query(User).order_by(User.id.asc()).all()
    if not users:
        print("No users registered yet.")
        return
    print(f"{'id':>4}  {'username':<24} {'email':<32} admin")
    print("-" * 72)
    for u in users:
        print(f"{u.id:>4}  {u.username:<24} {(u.email or ''):<32} "
              f"{'YES' if u.is_admin else '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", help="account username (case-insensitive)")
    ap.add_argument("--email", help="account email (case-insensitive)")
    ap.add_argument("--revoke", action="store_true",
                    help="remove admin instead of granting it")
    ap.add_argument("--logout", action="store_true",
                    help="revoke every session token for the account")
    ap.add_argument("--list", action="store_true", dest="list_users",
                    help="list users and exit")
    args = ap.parse_args()

    print(f"→ database: {DATABASE_URL.split('@')[-1]}")
    db = SessionLocal()
    try:
        if args.list_users or not (args.username or args.email):
            _print_users(db)
            return 0 if args.list_users else 2

        q = db.query(User)
        if args.username:
            q = q.filter(func.lower(User.username) == args.username.strip().lower())
        else:
            q = q.filter(func.lower(User.email) == args.email.strip().lower())
        user = q.first()
        if user is None:
            print("❌ No such user. Known accounts:")
            _print_users(db)
            return 1

        if args.revoke:
            admins = db.query(User).filter(User.is_admin.is_(True)).count()
            if user.is_admin and admins <= 1:
                print("❌ Refusing to revoke the last remaining admin.")
                return 1
            user.is_admin = False
        else:
            user.is_admin = True

        if args.logout:
            user.token_version = int(user.token_version or 0) + 1

        db.commit()
        db.refresh(user)
        print(f"✅ {user.username} (id={user.id}) is now "
              f"{'an ADMIN' if user.is_admin else 'a regular user'}"
              f"{'; all sessions revoked' if args.logout else ''}.")
        print("   Sign out and back in (or wait ~30s) for the UI to pick it up.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

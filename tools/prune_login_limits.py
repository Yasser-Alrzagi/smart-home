"""Delete ONLY expired anti-abuse buckets; defaults to dry-run. No audit/session deletion."""

import argparse
from sqlalchemy import delete, func, select


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from app.core.database import session_scope
    from app.models import LoginRateBucket, utcnow

    with session_scope() as db:
        cutoff = utcnow()
        count = db.scalar(
            select(func.count())
            .select_from(LoginRateBucket)
            .where(LoginRateBucket.expires_at <= cutoff)
        )
        if args.apply:
            db.execute(
                delete(LoginRateBucket).where(LoginRateBucket.expires_at <= cutoff)
            )
    print(
        f"Expired buckets: {count}; {'removed' if args.apply else 'dry-run; pass --apply to remove'}."
    )


if __name__ == "__main__":
    main()

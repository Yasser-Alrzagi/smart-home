"""Retired one-off generator. The original is archived as non-executable text.

Do not regenerate an applied revision from current ORM metadata. The legacy
bodies also predate the InnoDB downgrade fix. Use a new Alembic revision instead.
"""


def main() -> None:
    raise SystemExit(
        "This historical assembler is retired and will not overwrite a migration. "
        "See alembic/superseded/assemble_revision_legacy.py.txt for reference."
    )


if __name__ == "__main__":
    main()

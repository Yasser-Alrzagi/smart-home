"""One-time first administrator. Passwords are never accepted as command-line arguments."""

import argparse
import getpass
import sys


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        if message.startswith("unrecognized arguments:"):
            message = "Unrecognized arguments. Never supply passwords in command-line arguments."
        super().error(message)


def main():
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Explicit automation mode: one password line on stdin, never argv",
    )
    args = parser.parse_args()
    try:
        if args.password_stdin:
            password = sys.stdin.readline(2048).rstrip("\r\n")
        else:
            password = getpass.getpass("New administrator password: ")
            if password != getpass.getpass("Confirm password: "):
                parser.error("Passwords do not match.")
        from pydantic import ValidationError
        from sqlalchemy.exc import SQLAlchemyError
        from app.core.database import session_scope
        from app.core.errors import AppError
        from app.schemas.identity import BootstrapAdmin
        from app.services.accounts import bootstrap_admin

        try:
            data = BootstrapAdmin(
                username=args.username, email=args.email, password=password
            )
        except ValidationError:
            parser.error(
                "Invalid input: check username, email, and the documented password policy."
            )
        try:
            with session_scope() as db:
                user = bootstrap_admin(db, data)
                user_id = user.user_id
        except AppError as exc:
            parser.error(exc.detail)
        except SQLAlchemyError:
            parser.error(
                "Database operation failed. Check connectivity and apply migrations first; details redacted."
            )
        print(
            f"First administrator created: {user_id}. No password or token is printed."
        )
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "Cancelled; no credentials printed.\n")


if __name__ == "__main__":
    main()

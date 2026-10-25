"""Create the initial CampusCare administrator account safely.

Run from the project folder:
    .venv\\Scripts\\python.exe create_admin.py

You will be prompted for a username, email and password. Nothing is printed.
"""

import getpass
import os
import re
import sys

from werkzeug.security import generate_password_hash

from app import create_app
from database import create_user, email_exists, username_exists


def main():
    app = create_app()
    with app.app_context():
        print("Create initial CampusCare admin account")
        username = input("Admin username: ").strip()
        email = input("Admin email: ").strip().lower()
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")

        errors = []
        if not re.match(r"^[A-Za-z0-9_]{3,30}$", username):
            errors.append("Username must be 3-30 characters (letters, numbers, underscore).")
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Please enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if username_exists(app.config["DATABASE_PATH"], username):
            errors.append("That username is already taken.")
        if email_exists(app.config["DATABASE_PATH"], email):
            errors.append("That email is already registered.")

        if errors:
            print("Cannot create admin:")
            for error in errors:
                print(f" - {error}")
            sys.exit(1)

        password_hash = generate_password_hash(password)
        create_user(app.config["DATABASE_PATH"], username, email, password_hash, "admin")
        print("Admin account created successfully.")


if __name__ == "__main__":
    main()

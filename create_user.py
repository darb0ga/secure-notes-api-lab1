"""Create one local account without storing the password in source code."""

import getpass

from app import create_app


def main():
    app = create_app()
    app.initialize_database()
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    app.create_user(username, password)
    print("User created")


if __name__ == "__main__":
    main()

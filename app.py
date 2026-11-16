"""Small REST API for the first information security lab."""

import html
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt
from flask import Flask, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("DATABASE", str(Path(__file__).with_name("notes.db"))),
        SECRET_KEY=os.environ.get("JWT_SECRET", ""),
        MAX_CONTENT_LENGTH=16 * 1024,
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)
    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters")

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def initialize_database():
        with app.app_context():
            db = get_db()
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );
                """
            )
            db.commit()

    def create_user(username, password):
        if not username or not password:
            raise ValueError("Username and password are required")
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password, method="scrypt")),
            )
            db.commit()

    app.initialize_database = initialize_database
    app.create_user = create_user

    def require_token(view):
        @wraps(view)
        def decorated(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            scheme, separator, token = header.partition(" ")
            if scheme.lower() != "bearer" or not separator or not token:
                return jsonify(error="Bearer token required"), 401
            try:
                payload = jwt.decode(
                    token,
                    app.config["SECRET_KEY"],
                    algorithms=["HS256"],
                    issuer="secure-notes-api",
                    options={"require": ["sub", "iat", "exp", "iss"]},
                )
                user_id = int(payload["sub"])
            except (jwt.InvalidTokenError, ValueError, TypeError):
                return jsonify(error="Invalid or expired token"), 401
            user = get_db().execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                return jsonify(error="Invalid user"), 401
            g.user_id = user_id
            return view(*args, **kwargs)

        return decorated

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/auth/login")
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("username"), str) or not isinstance(data.get("password"), str):
            return jsonify(error="username and password must be strings"), 400
        user = get_db().execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (data["username"],)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], data["password"]):
            return jsonify(error="Invalid credentials"), 401
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": str(user["id"]),
                "iat": now,
                "exp": now + timedelta(minutes=30),
                "iss": "secure-notes-api",
            },
            app.config["SECRET_KEY"],
            algorithm="HS256",
        )
        return jsonify(access_token=token, token_type="Bearer", expires_in=1800)

    @app.get("/api/data")
    @require_token
    def list_notes():
        rows = get_db().execute(
            "SELECT id, title, body FROM notes WHERE user_id = ? ORDER BY id", (g.user_id,)
        ).fetchall()
        return jsonify(items=[{"id": row["id"], "title": html.escape(row["title"]), "body": html.escape(row["body"])} for row in rows])

    @app.post("/api/data")
    @require_token
    def add_note():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not isinstance(data.get("body"), str):
            return jsonify(error="title and body must be strings"), 400
        title, body = data["title"].strip(), data["body"].strip()
        if not title or not body or len(title) > 200 or len(body) > 2000:
            return jsonify(error="title/body cannot be empty or exceed 200/2000 characters"), 400
        db = get_db()
        cursor = db.execute(
            "INSERT INTO notes (user_id, title, body) VALUES (?, ?, ?)",
            (g.user_id, title, body),
        )
        db.commit()
        return jsonify(id=cursor.lastrowid, title=html.escape(title), body=html.escape(body)), 201

    return app


if __name__ == "__main__":
    application = create_app()
    application.initialize_database()
    application.run(host="127.0.0.1", port=5000, debug=False)

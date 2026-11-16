"""Run a real local HTTP demonstration without leaving a server running."""

import json
import tempfile
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from werkzeug.serving import make_server

from app import create_app


def call(method, path, data=None, token=None):
    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"http://127.0.0.1:5001{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


with tempfile.TemporaryDirectory() as directory:
    app = create_app({"DATABASE": str(Path(directory) / "demo.db"), "SECRET_KEY": "local-demo-secret-not-for-production-123456"})
    app.initialize_database()
    app.create_user("student", "Demo-Password-123!")
    server = make_server("127.0.0.1", 5001, app)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        status, body = call("GET", "/api/data")
        print(f"GET /api/data without token -> {status}: {body}")
        status, body = call("POST", "/auth/login", {"username": "student", "password": "Demo-Password-123!"})
        token = body["access_token"]
        print(f"POST /auth/login -> {status}: JWT issued (token omitted)")
        status, body = call("POST", "/api/data", {"title": "<script>alert(1)</script>", "body": "Demo note"}, token)
        print(f"POST /api/data with JWT -> {status}: {body}")
        status, body = call("GET", "/api/data", token=token)
        print(f"GET /api/data with JWT -> {status}: {body}")
    finally:
        server.shutdown()
        thread.join()

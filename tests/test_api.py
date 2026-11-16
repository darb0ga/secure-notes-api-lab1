import os
import sqlite3
import tempfile
import unittest

from app import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp_dir.name, "test.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.database, "SECRET_KEY": "test-secret-only-please-do-not-use-in-production"})
        self.app.initialize_database()
        self.app.create_user("alice", "Strong-test-password-123!")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self):
        response = self.client.post("/auth/login", json={"username": "alice", "password": "Strong-test-password-123!"})
        self.assertEqual(response.status_code, 200)
        return response.json["access_token"]

    def test_authentication_and_access_control(self):
        self.assertEqual(self.client.get("/api/data").status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"username": "alice", "password": "wrong"}).status_code, 401)
        token = self.login()
        self.assertEqual(self.client.get("/api/data", headers={"Authorization": f"Bearer {token}"}).json, {"items": []})

    def test_sql_injection_does_not_bypass_login(self):
        response = self.client.post("/auth/login", json={"username": "alice' OR 1=1 --", "password": "anything"})
        self.assertEqual(response.status_code, 401)

    def test_xss_is_escaped_and_password_is_hashed(self):
        token = self.login()
        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.post("/api/data", headers=headers, json={"title": "<script>alert(1)</script>", "body": "<b>Hello</b>"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["title"], "&lt;script&gt;alert(1)&lt;/script&gt;")
        items = self.client.get("/api/data", headers=headers).json["items"]
        self.assertEqual(items[0]["body"], "&lt;b&gt;Hello&lt;/b&gt;")
        db = sqlite3.connect(self.database)
        try:
            stored = db.execute("SELECT password_hash FROM users WHERE username = ?", ("alice",)).fetchone()[0]
        finally:
            db.close()
        self.assertNotEqual(stored, "Strong-test-password-123!")
        self.assertTrue(stored.startswith("scrypt:"))

    def test_invalid_token_is_rejected(self):
        self.assertEqual(self.client.get("/api/data", headers={"Authorization": "Bearer invalid"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()

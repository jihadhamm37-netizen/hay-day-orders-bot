"""Tiny async ASGI test client (keeps cookies) — avoids extra test dependencies."""
from __future__ import annotations

import json
import uuid
from http.cookies import SimpleCookie
from urllib.parse import urlsplit


class Resp:
    def __init__(self, status: int, headers: list[tuple[bytes, bytes]], body: bytes):
        self.status_code = status
        self.headers = {k.decode().lower(): v.decode() for k, v in headers}
        self.raw_headers = headers
        self.content = body

    def json(self):
        return json.loads(self.content)

    @property
    def text(self):
        return self.content.decode()


class Client:
    def __init__(self, app):
        self.app = app
        self.cookies: dict[str, str] = {}

    async def request(self, method: str, url: str, json_body=None, headers: dict | None = None,
                      files: dict | None = None) -> Resp:
        parts = urlsplit(url)
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        body = b""
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs["content-type"] = "application/json"
        if files:
            boundary = uuid.uuid4().hex
            chunks = []
            for name, (filename, data) in files.items():
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                              f"Content-Type: text/csv\r\n\r\n".encode() + data + b"\r\n")
            body = b"".join(chunks) + f"--{boundary}--\r\n".encode()
            hdrs["content-type"] = f"multipart/form-data; boundary={boundary}"
        if self.cookies:
            hdrs["cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        hdrs["host"] = "test"
        hdrs["content-length"] = str(len(body))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": parts.path, "raw_path": parts.path.encode(), "query_string": parts.query.encode(),
                 "root_path": "", "headers": [(k.encode(), v.encode()) for k, v in hdrs.items()],
                 "client": ("127.0.0.1", 5000), "server": ("test", 80)}
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        out = {"status": 500, "headers": [], "body": b""}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"], out["headers"] = msg["status"], msg.get("headers", [])
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        await self.app(scope, receive, send)
        for k, v in out["headers"]:
            if k.lower() == b"set-cookie":
                c = SimpleCookie()
                c.load(v.decode())
                for name, morsel in c.items():
                    if morsel["max-age"] == "0" or morsel.value in ("", '""'):
                        self.cookies.pop(name, None)
                    else:
                        self.cookies[name] = morsel.value
        return Resp(out["status"], out["headers"], out["body"])

    def csrf(self) -> dict:
        return {"x-csrf-token": self.cookies.get("hd_csrf", "")}

    async def get(self, url, **kw):
        return await self.request("GET", url, **kw)

    async def post(self, url, json=None, csrf=True, **kw):
        h = kw.pop("headers", {}) or {}
        if csrf:
            h.update(self.csrf())
        return await self.request("POST", url, json_body=json, headers=h, **kw)

    async def patch(self, url, json=None):
        return await self.request("PATCH", url, json_body=json, headers=self.csrf())

    async def put(self, url, json=None):
        return await self.request("PUT", url, json_body=json, headers=self.csrf())

    async def delete(self, url):
        return await self.request("DELETE", url, headers=self.csrf())

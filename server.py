#!/usr/bin/env python3
"""MediSense AI web server - Python standard library ONLY.
No pip installs. Run:  python3 server.py   then open http://localhost:8000

Endpoints:
  GET  /              -> web UI (web/index.html)
  GET  /api/health    -> {"status": "ok"}
  POST /api/analyze   -> JSON {"text": "<prescription or lab report text>"}
                         returns the full structured analysis (medisense.engine)
Image OCR happens in the browser (Tesseract.js, printed text only) so no
image ever needs a heavy server model; the text it reads is sent here.
"""
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from medisense import analyze

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "web"), **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/health":
            return self._json({"status": "ok", "service": "medisense-ai"})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/analyze":
            return self._json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            text = str(body.get("text", ""))[:20000]
            if not text.strip():
                return self._json({"error": "empty text"}, 400)
            return self._json(analyze(text))
        except Exception as e:  # keep the API honest, never crash the server
            return self._json({"error": str(e)}, 500)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print("MediSense AI running at http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()

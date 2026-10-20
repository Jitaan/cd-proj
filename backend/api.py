# api.py - minimal HTTP API over service.py (stdlib only)
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from http.server import BaseHTTPRequestHandler, HTTPServer

import service

HOST = "127.0.0.1"
PORT = 8000


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/examples":
            self._json(service.list_examples())
        elif self.path == "/api/model":
            self._json(service.explain_model())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        if self.path == "/api/run":
            src = payload.get("source", "")
            mode = payload.get("mode", "ai")
            passes = payload.get("passes")
            lang = payload.get("lang", "mini")
            self._json(service.run_pipeline(src, mode=mode, passes=passes, lang=lang))
        elif self.path == "/api/compare":
            src = payload.get("source", "")
            self._json(service.compare_modes(src))
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("API on http://%s:%d" % (HOST, PORT))
    HTTPServer((HOST, PORT), Handler).serve_forever()

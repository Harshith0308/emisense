#!/usr/bin/env python3
"""
serve.py

Group 4 - Edge Computing (CSE 469), SRM AP
EMI source classification project.

Serves the repository on http://127.0.0.1:8000 (this laptop only, never the
network) and opens the live dashboard. The page reads the class list from
emi_classify/emi_model.h and the threshold from analysis/results.json.

    python dashboard/serve.py            then use Chrome or Edge
    python dashboard/serve.py --no-open  do not open a browser

Chrome and Edge can talk to the ESP32 over USB (Web Serial); Firefox cannot.
"""

import argparse
import functools
import http.server
import os
import threading
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """Never let the browser keep an old app.js or emi_model.h: after a
    retrain a cached class list would put the wrong names on the board's
    decisions."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    handler = functools.partial(NoCacheHandler, directory=ROOT)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/dashboard/"
        print(f"EMISense dashboard: {url}  (Chrome or Edge; Ctrl+C to stop)", flush=True)
        if not args.no_open:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        httpd.serve_forever()


if __name__ == "__main__":
    main()

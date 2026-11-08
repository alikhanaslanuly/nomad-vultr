import http.server
import socketserver
import json
import re
import sys
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SINK] %(message)s")

CANARY_REGEX = re.compile(r"AIRLOCK-CANARY-([a-zA-Z0-9_]+)")

class SinkHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_ANY(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        
        # Log intercepted connection
        client_ip = self.client_address[0]
        host_header = self.headers.get("Host", "unknown")
        logging.info("Intercepted %s %s from %s (Host: %s, %d bytes)",
                     self.command, self.path, client_ip, host_header, len(body))

        # Check for markers
        matches = CANARY_REGEX.findall(body.decode("utf-8", errors="ignore"))
        for m in matches:
            logging.warning("CRITICAL ALERT: Exfiltration attempt detected for marker AIRLOCK-CANARY-%s", m)

        # Catch-all reply (sink closes or returns simulated ok)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"AIRLOCK_HONEYNET_CAPTURED\n")

    do_GET = do_ANY
    do_POST = do_ANY
    do_PUT = do_ANY
    do_HEAD = do_ANY

if __name__ == "__main__":
    port = 80
    logging.info("Starting Honeynet Catch-all HTTP Sink on port %d...", port)
    with socketserver.TCPServer(("0.0.0.0", port), SinkHTTPHandler) as httpd:
        httpd.serve_forever()


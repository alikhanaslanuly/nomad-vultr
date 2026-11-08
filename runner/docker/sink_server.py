import http.server
import ipaddress
import json
import os
import socket
import socketserver
import struct
import threading

from runner.sink import HoneynetSink


sink = HoneynetSink()
output_lock = threading.Lock()
MAX_BODY = 65536
RUN_ID = os.environ.get("AIRLOCK_RUN_ID", "")


def publish(events: list[dict]) -> None:
    for event in events:
        with output_lock:
            print(
                json.dumps({**event, "run_id": RUN_ID}, separators=(",", ":")),
                flush=True,
            )


def dns_reply(packet: bytes, address: str) -> tuple[bytes, str]:
    if len(packet) < 12 or struct.unpack("!H", packet[4:6])[0] != 1:
        raise ValueError("One DNS question required")
    offset = 12
    labels = []
    while offset < len(packet):
        size = packet[offset]
        offset += 1
        if size == 0:
            break
        if size > 63 or offset + size > len(packet) or len(labels) > 127:
            raise ValueError("Invalid DNS question")
        labels.append(packet[offset : offset + size].decode("ascii"))
        offset += size
    if offset + 4 > len(packet):
        raise ValueError("Truncated DNS question")
    name = ".".join(labels)
    if len(name) > 253:
        raise ValueError("DNS name too long")
    qtype, qclass = struct.unpack("!HH", packet[offset : offset + 4])
    question = packet[12 : offset + 4]
    answer = qtype == 1 and qclass == 1
    header = packet[:2] + struct.pack("!HHHHH", 0x8180, 1, int(answer), 0, 0)
    record = (
        b"\xc0\x0c"
        + struct.pack("!HHIH", 1, 1, 0, 4)
        + ipaddress.IPv4Address(address).packed
        if answer
        else b""
    )
    return header + question + record, name


class DNSHandler(socketserver.BaseRequestHandler):
    def handle(self):
        packet, server_socket = self.request
        try:
            response, name = dns_reply(packet, self.server.sink_ip)
        except (ValueError, UnicodeDecodeError):
            return
        publish(
            sink.process_dns_query(name, self.client_address[0], self.server.sink_ip)
        )
        server_socket.sendto(response, self.client_address)


class HTTPHandler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):
        return

    def receive_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            body = bytearray()
            for _ in range(256):
                size = int(self.rfile.readline(128).split(b";", 1)[0].strip(), 16)
                if size == 0:
                    return bytes(body)
                if size > MAX_BODY - len(body):
                    raise ValueError("Body too large")
                body.extend(self.rfile.read(size))
                if self.rfile.read(2) != b"\r\n":
                    raise ValueError("Invalid chunk")
            raise ValueError("Too many chunks")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 <= size <= MAX_BODY:
            raise ValueError("Body too large")
        return self.rfile.read(size)

    def do_request(self):
        try:
            body = self.receive_body()
        except (ValueError, TimeoutError):
            publish(
                sink.process_http_request(
                    self.command,
                    self.headers.get("Host", ""),
                    self.path,
                    dict(self.headers),
                    b"",
                    self.client_address[0],
                    sink_ip=self.server.sink_ip,
                    body_truncated=True,
                )
            )
            self.send_error(413)
            return
        publish(
            sink.process_http_request(
                self.command,
                self.headers.get("Host", ""),
                self.path,
                dict(self.headers),
                body,
                self.client_address[0],
                sink_ip=self.server.sink_ip,
            )
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"AIRLOCK_HONEYNET_CAPTURED\n")

    do_GET = do_request
    do_POST = do_request
    do_PUT = do_request
    do_PATCH = do_request
    do_DELETE = do_request
    do_HEAD = do_request


def main():
    if not RUN_ID:
        raise RuntimeError("AIRLOCK_RUN_ID required")
    ip = os.environ.get("SINK_IP") or socket.gethostbyname(socket.gethostname())
    dns = socketserver.ThreadingUDPServer(("0.0.0.0", 53), DNSHandler)
    dns.sink_ip = ip
    dns.daemon_threads = True
    threading.Thread(target=dns.serve_forever, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 80), HTTPHandler)
    server.sink_ip = ip
    server.serve_forever()


if __name__ == "__main__":
    main()

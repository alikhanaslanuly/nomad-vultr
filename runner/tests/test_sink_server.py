import socket
import struct

import pytest

from runner.docker.sink_server import dns_reply
from runner.sink import HoneynetSink


def test_dns_reply_directs_test_domain_to_sink_and_preserves_transaction():
    query = (
        b"\x12\x34"
        + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0)
        + b"\x07airlock\x04test\x00"
        + struct.pack("!HH", 1, 1)
    )
    response, name = dns_reply(query, "10.77.0.2")
    assert name == "airlock.test"
    assert response[:2] == query[:2]
    assert response[-4:] == socket.inet_aton("10.77.0.2")
    assert struct.unpack("!H", response[6:8])[0] == 1


def test_dns_rejects_compressed_or_malformed_questions():
    query = b"\x12\x34" + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0) + b"\xc0\x0c"
    with pytest.raises(ValueError):
        dns_reply(query, "10.77.0.2")


def test_http_sink_events_come_from_received_metadata_and_body():
    events = HoneynetSink().process_http_request(
        "POST", "airlock.test", "/capture", {}, b"AIRLOCK-CANARY-aws_creds", "10.77.0.3"
    )
    assert events[0]["detail"]["http"] == {
        "method": "POST",
        "path": "/capture",
        "host": "airlock.test",
    }
    assert events[0]["detail"]["blocked"] is True
    assert any(
        event["kind"] == "canary" and event["detail"]["where"] == "http_body"
        for event in events
    )
    assert all(event["source"] == "host" for event in events)


class RequestSocket:
    def __init__(self, payload):
        import io

        self.input = io.BytesIO(payload)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, payload):
        self.output.extend(payload)

    def settimeout(self, value):
        return


def test_http_server_parses_received_chunked_body_and_records_source_and_destination(
    monkeypatch,
):
    from types import SimpleNamespace
    from runner.docker import sink_server

    events = []
    monkeypatch.setattr(sink_server, "publish", events.extend)
    body = b"AIRLOCK-CANARY-aws_creds"
    payload = (
        b"POST /capture HTTP/1.1\r\nHost: airlock.test\r\nTransfer-Encoding: chunked\r\n\r\n"
        + f"{len(body):x}\r\n".encode()
        + body
        + b"\r\n0\r\n\r\n"
    )
    request = RequestSocket(payload)
    sink_server.HTTPHandler(
        request, ("10.0.0.3", 12345), SimpleNamespace(sink_ip="10.0.0.2")
    )
    assert b"200 OK" in request.output
    assert events[0]["detail"]["ip"] == "10.0.0.2"
    assert events[0]["detail"]["client_ip"] == "10.0.0.3"
    assert events[0]["detail"]["bytes_out"] == len(body)
    assert events[1]["detail"]["where"] == "http_body"


def test_http_server_rejects_oversized_body_and_marks_capture_incomplete(monkeypatch):
    from types import SimpleNamespace
    from runner.docker import sink_server

    events = []
    monkeypatch.setattr(sink_server, "publish", events.extend)
    request = RequestSocket(
        b"POST /capture HTTP/1.1\r\nHost: airlock.test\r\nContent-Length: 65537\r\n\r\n"
    )
    sink_server.HTTPHandler(
        request, ("10.0.0.3", 12345), SimpleNamespace(sink_ip="10.0.0.2")
    )
    assert b"413" in request.output
    assert events[0]["detail"]["body_truncated"] is True
    assert not any(event["kind"] == "canary" for event in events)


def test_unknown_marker_ids_are_not_presented_as_seeded_canaries():
    from runner.sink import CanaryDetector

    assert CanaryDetector.inspect_data("AIRLOCK-CANARY-made_up", "http_body") == []
    hits = CanaryDetector.inspect_data("sec_AIRLOCK-CANARY-dotenv_key", "http_body")
    assert hits[0]["canary_id"] == "dotenv"

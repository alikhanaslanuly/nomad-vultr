import base64
import binascii
import re
from datetime import datetime, timezone


MARKER = re.compile(
    r"AIRLOCK-CANARY-(aws_creds|ssh_key|npmrc|gh_token|dotenv|kube)(?![A-Za-z0-9])"
)


class CanaryDetector:
    @staticmethod
    def inspect_data(data: bytes | str, location: str) -> list[dict]:
        text = (
            data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        )
        candidates = [(text, "raw")]
        for value in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", text):
            try:
                decoded = base64.b64decode(value, validate=True).decode(
                    "utf-8", errors="replace"
                )
                candidates.append((decoded, "base64"))
            except (binascii.Error, ValueError):
                continue
        for value in re.findall(r"(?:[0-9A-Fa-f]{2}){8,}", text):
            candidates.append(
                (bytes.fromhex(value).decode("utf-8", errors="replace"), "hex")
            )
        hits: dict[tuple[str, str], dict] = {}
        for value, encoding in candidates:
            for match in MARKER.finditer(value):
                hits[(match[1], encoding)] = {
                    "canary_id": match[1],
                    "trigger": "exfil_attempt",
                    "marker": match[0],
                    "where": location,
                    "encoding": encoding,
                }
        return list(hits.values())


class HoneynetSink:
    @staticmethod
    def envelope(kind: str, detail: dict) -> dict:
        return {
            "kind": kind,
            "detail": detail,
            "severity": "alert" if kind == "canary" else "warn",
            "observer": "sink",
            "source": "host",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def process_http_request(
        self,
        method: str,
        host: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        remote_ip: str,
        port: int = 80,
        sink_ip: str | None = None,
        body_truncated: bool = False,
    ) -> list[dict]:
        detail = {
            "op": "http",
            "dest": host,
            "client_ip": remote_ip,
            "port": port,
            "proto": "tcp",
            "blocked": True,
            "bytes_out": len(body),
            "intercepted": True,
            "http": {"method": method, "path": path, "host": host},
        }
        if body_truncated:
            detail["body_truncated"] = True
        if sink_ip:
            detail["ip"] = sink_ip
        events = [self.envelope("net", detail)]
        for value, location in [
            (path, "http_url"),
            (str(headers), "http_headers"),
            (body, "http_body"),
        ]:
            events.extend(
                self.envelope("canary", hit)
                for hit in CanaryDetector.inspect_data(value, location)
            )
        return events

    def process_dns_query(
        self, query_name: str, client_ip: str, sink_ip: str
    ) -> list[dict]:
        events = [
            self.envelope(
                "net",
                {
                    "op": "dns",
                    "dest": query_name,
                    "ip": sink_ip,
                    "port": 53,
                    "proto": "udp",
                    "blocked": True,
                    "intercepted": True,
                    "client_ip": client_ip,
                },
            )
        ]
        events.extend(
            self.envelope("canary", hit)
            for hit in CanaryDetector.inspect_data(query_name, "dns_name")
        )
        return events

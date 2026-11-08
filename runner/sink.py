import re
import base64
import binascii
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

log = logging.getLogger(__name__)

CANARY_PREFIX = "AIRLOCK-CANARY-"
CANARY_REGEX = re.compile(r"AIRLOCK-CANARY-([a-zA-Z0-9_]+)")


class CanaryDetector:
    @staticmethod
    def inspect_data(data: bytes | str, location: str) -> List[Dict[str, Any]]:
        """
        Inspects payload data (HTTP body, URL, header, DNS query) for canary markers in:
        1) raw text
        2) base64 encoded strings
        3) hex encoded strings
        Returns list of canary detection dicts.
        """
        detections = []
        if isinstance(data, str):
            raw_str = data
            raw_bytes = data.encode("utf-8", errors="ignore")
        else:
            raw_bytes = data
            raw_str = data.decode("utf-8", errors="ignore")

        # 1. Raw search
        for match in CANARY_REGEX.finditer(raw_str):
            canary_id = match.group(1)
            marker = match.group(0)
            detections.append({
                "canary_id": canary_id,
                "trigger": "exfil_attempt",
                "marker": marker,
                "where": location,
                "encoding": "raw"
            })

        # 2. Base64 search
        # Look for potential base64 chunks (min 16 chars)
        b64_candidates = re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", raw_str)
        for cand in b64_candidates:
            try:
                decoded = base64.b64decode(cand, validate=False).decode("utf-8", errors="ignore")
                for match in CANARY_REGEX.finditer(decoded):
                    canary_id = match.group(1)
                    detections.append({
                        "canary_id": canary_id,
                        "trigger": "exfil_attempt",
                        "marker": match.group(0),
                        "where": location,
                        "encoding": "base64"
                    })
            except Exception:
                pass

        # 3. Hex search
        hex_candidates = re.findall(r"(?:[0-9a-fA-F]{2}){8,}", raw_str)
        for cand in hex_candidates:
            try:
                decoded = bytes.fromhex(cand).decode("utf-8", errors="ignore")
                for match in CANARY_REGEX.finditer(decoded):
                    canary_id = match.group(1)
                    detections.append({
                        "canary_id": canary_id,
                        "trigger": "exfil_attempt",
                        "marker": match.group(0),
                        "where": location,
                        "encoding": "hex"
                    })
            except Exception:
                pass

        # Deduplicate detections by (canary_id, where, encoding)
        unique = []
        seen = set()
        for d in detections:
            key = (d["canary_id"], d["where"], d["encoding"])
            if key not in seen:
                seen.add(key)
                unique.append(d)

        return unique


class HoneynetSink:
    def __init__(self):
        self.detector = CanaryDetector()

    def process_http_request(
        self,
        method: str,
        host: str,
        path: str,
        headers: Dict[str, str],
        body: bytes,
        remote_ip: str,
        port: int = 80
    ) -> List[Dict[str, Any]]:
        """
        Processes an outbound HTTP request intercepted by the honeynet sink.
        Generates 'net' and potential 'canary' exfiltration events.
        """
        now = datetime.now(timezone.utc).isoformat()
        events = []

        # 1. Base net event
        net_detail = {
            "op": "http",
            "dest": host,
            "ip": remote_ip,
            "port": port,
            "proto": "tcp",
            "blocked": True,
            "bytes_out": len(body),
            "http": {
                "method": method,
                "path": path,
                "host": host
            }
        }
        events.append({
            "kind": "net",
            "severity": "warn",
            "observer": "sink",
            "source": "host",
            "ts": now,
            "detail": net_detail
        })

        # 2. Check for canary markers in URL, Headers, and Body
        where_checks = [
            (path, "http_body" if "/upload" in path or "/exfil" in path else "http_body"),
            (str(headers), "argv" if "header" in path else "http_body"),
            (body, "http_body")
        ]

        for payload, loc in where_checks:
            canary_hits = self.detector.inspect_data(payload, loc)
            for hit in canary_hits:
                events.append({
                    "kind": "canary",
                    "severity": "alert",
                    "observer": "sink",
                    "source": "host",
                    "ts": now,
                    "detail": hit
                })

        return events

    def process_dns_query(self, query_name: str, client_ip: str) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        events = []

        net_detail = {
            "op": "dns",
            "dest": query_name,
            "ip": "10.77.0.2",
            "port": 53,
            "proto": "udp",
            "blocked": True,
            "bytes_out": len(query_name)
        }
        events.append({
            "kind": "net",
            "severity": "warn",
            "observer": "sink",
            "source": "host",
            "ts": now,
            "detail": net_detail
        })

        canary_hits = self.detector.inspect_data(query_name, "dns_name")
        for hit in canary_hits:
            events.append({
                "kind": "canary",
                "severity": "alert",
                "observer": "sink",
                "source": "host",
                "ts": now,
                "detail": hit
            })

        return events


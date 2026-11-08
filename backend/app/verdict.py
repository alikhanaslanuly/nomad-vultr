from dataclasses import dataclass, field
from typing import Iterable

ALERT_WEIGHT = 40
WARN_WEIGHT = 15
SCORE_CAP = 100
MALICIOUS_FLOOR = 85

SUSPICIOUS_BINARIES = {"curl", "wget", "nc", "ssh", "scp", "base64"}


@dataclass
class Finding:
    id: str
    severity: str
    rule: str
    claim: str
    observed: str
    evidence_event_ids: list[str] = field(default_factory=list)
    code_ref: dict | None = None


def _first_argv(event: dict) -> list[str]:
    d = event.get("detail") or {}
    argv = d.get("argv")
    return argv if isinstance(argv, list) else []


def _has_suspicious_proc(events: list[dict]) -> list[dict]:
    hits = []
    for e in events:
        if e.get("kind") != "proc":
            continue
        argv = _first_argv(e)
        if argv and argv[0] in SUSPICIOUS_BINARIES:
            hits.append(e)
    return hits


def _canary_reads(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        if e.get("kind") == "file" and (e.get("detail") or {}).get("canary"):
            op = (e.get("detail") or {}).get("op")
            if op in ("read", "open"):
                out.append(e)
    return out


def _canary_exfil(events: list[dict]) -> list[dict]:
    return [e for e in events
            if e.get("kind") == "canary" and (e.get("detail") or {}).get("trigger") == "exfil_attempt"]


def _net_blocked(events: list[dict]) -> list[dict]:
    return [e for e in events
            if e.get("kind") == "net" and (e.get("detail") or {}).get("blocked") is True]


def _limit_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("kind") == "limit"]


def _idx(events: list[dict], ev: dict) -> int:
    try:
        return events.index(ev)
    except ValueError:
        return -1


def evaluate(events_by_profile: dict[str, list[dict]]) -> tuple[str, int, list[Finding]]:
    """events_by_profile: {profile: [events]}"""
    findings: list[Finding] = []
    severity_hits = {"alert": 0, "warn": 0}
    saw_exfil_rule = False

    per_profile_alerts: dict[str, int] = {}

    for profile, events in events_by_profile.items():
        n_alerts = 0
        cr = _canary_reads(events)
        ex = _canary_exfil(events)
        nb = _net_blocked(events)
        sp = _has_suspicious_proc(events)
        lim = _limit_events(events)

        # canary_read
        if cr:
            findings.append(Finding(
                id=f"canary_read_{profile}", severity="alert", rule="canary_read",
                claim="No credential access", observed=f"Read canary file(s) in profile={profile}",
                evidence_event_ids=[e["id"] for e in cr],
            ))
            severity_hits["alert"] += 1; n_alerts += 1

        # net_exfil_after_canary
        if cr and (nb or ex):
            first_canary = _idx(events, cr[0])
            later_net = [e for e in nb if _idx(events, e) > first_canary]
            if later_net or ex:
                findings.append(Finding(
                    id=f"net_exfil_after_canary_{profile}", severity="alert",
                    rule="net_exfil_after_canary",
                    claim="No network activity", observed=f"Canary read followed by blocked egress in {profile}",
                    evidence_event_ids=[e["id"] for e in (later_net or ex)],
                ))
                severity_hits["alert"] += 1; n_alerts += 1; saw_exfil_rule = True

        # exfil_marker_seen
        if ex:
            findings.append(Finding(
                id=f"exfil_marker_{profile}", severity="alert", rule="exfil_marker_seen",
                claim="No exfiltration", observed="Canary marker seen in outbound request body",
                evidence_event_ids=[e["id"] for e in ex],
            ))
            severity_hits["alert"] += 1; n_alerts += 1; saw_exfil_rule = True

        # net_attempt (warn only if not already alerted via exfil)
        if nb and not (cr and (nb or ex)):
            findings.append(Finding(
                id=f"net_attempt_{profile}", severity="warn", rule="net_attempt",
                claim="Offline utility", observed="Blocked egress attempt",
                evidence_event_ids=[e["id"] for e in nb],
            ))
            severity_hits["warn"] += 1

        # suspicious_proc
        if sp:
            findings.append(Finding(
                id=f"suspicious_proc_{profile}", severity="warn", rule="suspicious_proc",
                claim="No shell tools used", observed="curl/wget/nc/base64 executed",
                evidence_event_ids=[e["id"] for e in sp],
            ))
            severity_hits["warn"] += 1

        # resource_abuse
        if lim:
            findings.append(Finding(
                id=f"limit_{profile}", severity="warn", rule="resource_abuse",
                claim="Runs anywhere", observed="Resource limit hit",
                evidence_event_ids=[e["id"] for e in lim],
            ))
            severity_hits["warn"] += 1

        per_profile_alerts[profile] = n_alerts

    # env_gated: alerts in one profile but not others
    if len(events_by_profile) > 1:
        vals = set(per_profile_alerts.values())
        if 0 in vals and any(v > 0 for v in vals):
            findings.append(Finding(
                id="env_gated", severity="warn", rule="env_gated",
                claim="Same behaviour everywhere", observed="Behaviour only in some profiles",
                evidence_event_ids=[],
            ))
            severity_hits["warn"] += 1

    # score
    score = min(SCORE_CAP, severity_hits["alert"] * ALERT_WEIGHT + severity_hits["warn"] * WARN_WEIGHT)

    # verdict
    if saw_exfil_rule:
        verdict = "MALICIOUS"
        score = max(score, MALICIOUS_FLOOR)
    elif severity_hits["alert"] > 0 or severity_hits["warn"] > 0:
        verdict = "SUSPICIOUS"
    elif events_by_profile and any(len(v) > 0 for v in events_by_profile.values()):
        verdict = "SAFE_OBSERVED"
    else:
        verdict = "ERROR"

    return verdict, score, findings
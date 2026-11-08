import base64
from runner.sink import CanaryDetector

def test_raw_marker_detection():
    data = "Attempting exfil of key: AIRLOCK-CANARY-aws_creds"
    hits = CanaryDetector.inspect_data(data, "http_body")
    assert len(hits) == 1
    assert hits[0]["canary_id"] == "aws_creds"
    assert hits[0]["encoding"] == "raw"

def test_base64_marker_detection():
    secret = "export AWS_SECRET_ACCESS_KEY=AIRLOCK-CANARY-aws_creds-secret-123456"
    b64_val = base64.b64encode(secret.encode()).decode()
    payload = f"data={b64_val}&status=ok"
    hits = CanaryDetector.inspect_data(payload, "http_body")
    assert any(h["canary_id"] == "aws_creds" and h["encoding"] == "base64" for h in hits)

def test_hex_marker_detection():
    secret = "AIRLOCK-CANARY-npmrc"
    hex_val = secret.encode().hex()
    payload = f"payload={hex_val}"
    hits = CanaryDetector.inspect_data(payload, "http_body")
    assert any(h["canary_id"] == "npmrc" and h["encoding"] == "hex" for h in hits)

if __name__ == "__main__":
    test_raw_marker_detection()
    test_base64_marker_detection()
    test_hex_marker_detection()
    print("Canary detection tests PASSED!")


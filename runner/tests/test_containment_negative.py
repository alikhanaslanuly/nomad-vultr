from runner.models import RunManifest, FileSpec
from runner.executor import SandboxExecutor, BLACKLISTED_ENV_PREFIXES


def test_path_traversal_forbidden():
    manifest = RunManifest(
        run_id="run_test_traversal",
        entrypoint=["bash", "work/run.sh"],
        files=[FileSpec(path="../etc/passwd", content_b64="dGVzdA==")],
    )
    executor = SandboxExecutor(manifest)
    try:
        executor.validate_manifest()
        assert False, "Should have raised ValueError on path traversal"
    except ValueError as e:
        assert "forbidden" in str(e)


def test_absolute_path_forbidden():
    manifest = RunManifest(
        run_id="run_test_abs",
        entrypoint=["bash", "work/run.sh"],
        files=[FileSpec(path="/root/.ssh/id_rsa", content_b64="dGVzdA==")],
    )
    executor = SandboxExecutor(manifest)
    try:
        executor.validate_manifest()
        assert False, "Should have raised ValueError on absolute path"
    except ValueError as e:
        assert "forbidden" in str(e)


def test_blacklisted_env_forbidden():
    manifest = RunManifest(
        run_id="run_test_env",
        entrypoint=["bash", "work/run.sh"],
        env={"VULTR_API_KEY": "secret-12345"},
    )
    executor = SandboxExecutor(manifest)
    try:
        executor.validate_manifest()
        assert False, "Should have raised ValueError on forbidden env"
    except ValueError as e:
        assert "forbidden" in str(e)


def test_secret_hygiene_check():

    test_env = {
        "PATH": "/usr/bin",
        "INFERENCE_API_KEY": "inf_test_secret",
        "VULTR_API_KEY": "vultr_sec_test",
        "RUNNER_TOKEN": "runner_token_sec",
        "RECEIPT_SIGNING_KEY": "rcp_sign_secret",
    }

    cleaned_env = {
        k: v
        for k, v in test_env.items()
        if not any(k.startswith(p) for p in BLACKLISTED_ENV_PREFIXES)
    }
    assert "INFERENCE_API_KEY" not in cleaned_env
    assert "VULTR_API_KEY" not in cleaned_env
    assert "RUNNER_TOKEN" not in cleaned_env
    assert "RECEIPT_SIGNING_KEY" not in cleaned_env


if __name__ == "__main__":
    test_path_traversal_forbidden()
    test_absolute_path_forbidden()
    test_blacklisted_env_forbidden()
    test_secret_hygiene_check()
    print("Negative containment and secret hygiene tests PASSED!")

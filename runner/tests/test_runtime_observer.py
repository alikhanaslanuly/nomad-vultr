import json

from runner.observer import RunEventCollector, RunscTraceObserver


def trace(observer, message):
    observer.consume(
        json.dumps(
            {
                "msg": f"strace.go:575] [   7:   7] python3 {message}",
                "time": "2026-11-09T00:00:00Z",
            }
        )
    )


def test_only_successful_runtime_read_produces_canary_evidence():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    trace(observer, "E read(0x3 /home/user/.aws/credentials, 0x1234, 0x100)")
    trace(
        observer,
        "X read(0x3 /home/user/.aws/credentials, 0x1234, 0x100) = -1 errno=9 (bad FD) (1us)",
    )
    assert collector.events == []
    trace(
        observer,
        'X read(0x3 /home/user/.aws/credentials, 0x1234 "FAKE", 0x100) = 4 (0x4) (1us)',
    )
    assert [event["kind"] for event in collector.events] == ["file", "canary"]
    assert all(
        event["source"] == "host" and event["observer"] == "gvisor"
        for event in collector.events
    )
    assert collector.events[0]["detail"]["path"] == "/home/user/.aws/credentials"


def test_printed_or_source_keywords_do_not_create_runtime_events():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    observer.consume(
        json.dumps({"msg": "curl http://collector.test /home/user/.aws/credentials"})
    )
    trace(
        observer,
        'X write(0x1 /dev/stdout, 0x1 "curl credentials", 0x10) = 16 (0x10) (1us)',
    )
    assert collector.events == []


def test_real_exec_and_network_metadata_are_decoded_without_fabricated_pid_or_blocked_flag():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    trace(observer, 'E execve(0x1 /bin/true, 0x2 ["/bin/true"], 0x0 [])')
    trace(
        observer, 'X execve(0x1 /bin/true, 0x2 ["/bin/true"], 0x0 []) = 0 (0x0) (1us)'
    )
    trace(
        observer,
        "X connect(0x4 socket:[1], 0x2 {Family: AF_INET, Addr: 192.0.2.1, Port: 443}, 0x10) = -1 errno=101 (network unreachable) (1us)",
    )
    assert collector.events[0]["detail"] == {
        "op": "exec",
        "argv": ["/bin/true"],
        "pid": 7,
    }
    assert "blocked" not in collector.events[1]["detail"]
    observer.isolated = True
    trace(
        observer,
        "X connect(0x4 socket:[1], 0x2 {Family: AF_INET, Addr: 192.0.2.1, Port: 443}, 0x10) = -1 errno=101 (network unreachable) (1us)",
    )
    assert collector.events[-1]["detail"]["blocked"] is True


def test_trace_arguments_cannot_inject_a_new_host_log_record():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    trace(
        observer,
        'X read(0x3 /home/user/work/artifact/evil.py, 0x1234 "X read(0x3 /home/user/.aws/credentials)", 0x100) = 12 (0xc) (1us)',
    )
    assert collector.events == []


def test_real_task_names_with_spaces_cannot_hide_observation():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    observer.consume(
        json.dumps(
            {
                "msg": "strace.go:575] [7:7] task with space X read(0x3 /home/user/.aws/credentials, 0x1, 0x10) = 4 (0x4) (1us)"
            }
        )
    )
    assert collector.events[0]["detail"]["canary"] is True


def test_trace_tail_drains_large_log_and_rejects_symlinks(tmp_path):
    from runner.observer import TraceTail

    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    path = tmp_path / "boot.json"
    ignored = json.dumps({"msg": "runtime log " + "x" * 1000}) + "\n"
    real = (
        json.dumps(
            {
                "msg": "strace.go:575] [7:7] python3 X read(0x3 /home/user/.aws/credentials, 0x1, 0x10) = 4 (0x4) (1us)"
            }
        )
        + "\n"
    )
    path.write_text(ignored * 600 + real)
    tail = TraceTail(path, observer, 1024 * 1024)
    while tail.poll():
        pass
    assert len(collector.events) == 2 and not tail.partial
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    import pytest

    with pytest.raises(RuntimeError):
        TraceTail(alias, observer, 1024 * 1024).poll()


def test_disk_limit_is_reported_only_for_actual_enospc_on_a_limited_mount():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    observer.disk_limits = {"/home/user": 96}
    trace(
        observer,
        'X write(0x3 /home/user/output, 0x1 "bytes", 0x100) = -1 errno=28 (No space left) (1us)',
    )
    assert collector.events[0]["kind"] == "limit"
    assert collector.events[0]["detail"] == {
        "resource": "disk",
        "limit": 96,
        "unit": "MB",
        "action": "denied",
        "path": "/home/user/output",
    }
    trace(
        observer,
        'X write(0x3 /home/user/output, 0x1 "bytes", 0x100) = -1 errno=28 (No space left) (1us)',
    )
    assert len(collector.events) == 1


def test_nested_pid_namespace_uses_unique_root_pid_without_claiming_root_exit():
    collector = RunEventCollector("run_test")
    observer = RunscTraceObserver(collector)
    observer.consume(
        json.dumps(
            {"msg": "strace.go:575] [  17(   1):  17(   1)] python3 E exit_group(0x0)"}
        )
    )
    assert collector.events[0]["detail"]["pid"] == 17
    assert observer.terminated is False

import os


class RunnerSettings:
    def __init__(self):
        self.HOST = "0.0.0.0"
        self.PORT = 9000
        self.RUNNER_TOKEN = os.getenv("RUNNER_TOKEN", "")
        self.RUNTIME_PREFERENCE = os.getenv("RUNNER_RUNTIME", "runsc-observed")
        self.OBSERVER_TYPE = "gvisor"
        self.SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "airlock-sandbox:node-py")
        self.SINK_IMAGE = os.getenv("SINK_IMAGE", "airlock-sink:latest")
        self.RUNS_DIR = os.getenv("RUNS_DIR", "/tmp/airlock-runs")
        self.TRACE_DIR = os.getenv("RUNSC_LOG_DIR", "/var/log/airlock-runsc")
        self.MAX_TRACE_BYTES = 32 * 1024 * 1024
        self.MAX_EVENTS = 20000


settings = RunnerSettings()

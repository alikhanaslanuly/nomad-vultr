import os

try:
    from pydantic_settings import BaseSettings

    class RunnerSettings(BaseSettings):
        HOST: str = "0.0.0.0"
        PORT: int = 9000
        RUNNER_TOKEN: str = os.getenv("RUNNER_TOKEN", "airlock-runner-token")
        RUNTIME_PREFERENCE: str = os.getenv("RUNNER_RUNTIME", "runsc")  # runsc or runc
        OBSERVER_TYPE: str = os.getenv("RUNNER_OBSERVER", "gvisor")     # gvisor or strace
        SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "airlock-sandbox:node-py")
        RUNS_DIR: str = os.getenv("RUNS_DIR", "/tmp/airlock-runs")
        HONEYNET_NETWORK: str = os.getenv("HONEYNET_NETWORK", "airlock-honeynet")
        SINK_HOST: str = os.getenv("SINK_HOST", "10.77.0.2")

    settings = RunnerSettings()

except ImportError:
    class RunnerSettings:
        def __init__(self):
            self.HOST: str = "0.0.0.0"
            self.PORT: int = 9000
            self.RUNNER_TOKEN: str = os.getenv("RUNNER_TOKEN", "airlock-runner-token")
            self.RUNTIME_PREFERENCE: str = os.getenv("RUNNER_RUNTIME", "runsc")
            self.OBSERVER_TYPE: str = os.getenv("RUNNER_OBSERVER", "gvisor")
            self.SANDBOX_IMAGE: str = os.getenv("SANDBOX_IMAGE", "airlock-sandbox:node-py")
            self.RUNS_DIR: str = os.getenv("RUNS_DIR", "/tmp/airlock-runs")
            self.HONEYNET_NETWORK: str = os.getenv("HONEYNET_NETWORK", "airlock-honeynet")
            self.SINK_HOST: str = os.getenv("SINK_HOST", "10.77.0.2")

    settings = RunnerSettings()

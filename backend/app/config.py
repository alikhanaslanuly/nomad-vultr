
import os


class Settings:
    def __init__(self):
        self.DATABASE_URL = os.getenv(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./airlock.db"
        )

        self.CORS_ORIGINS = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000"
        )

        self.RUNNER_URL = os.getenv("RUNNER_URL", "")
        self.RUNNER_TOKEN = os.getenv(
            "RUNNER_TOKEN",
            "airlock-runner-token"
        )

        self.USE_STUB_RUNNER = os.getenv(
            "USE_STUB_RUNNER",
            "0"
        ).lower() in ("1", "true", "yes")

        self.INFERENCE_BASE_URL = os.getenv(
            "INFERENCE_BASE_URL",
            "https://api.vultrinference.com/v1"
        )

        self.INFERENCE_API_KEY = os.getenv(
            "INFERENCE_API_KEY",
            "not-configured"
        )

        self.INFERENCE_MODEL_PLANNER = os.getenv(
            "INFERENCE_MODEL_PLANNER",
            "mistral-nemo"
        )

        self.INFERENCE_MODEL_EXPLAINER = os.getenv(
            "INFERENCE_MODEL_EXPLAINER",
            "mistral-nemo"
        )

        self.RECEIPT_SIGNING_KEY = os.getenv(
            "RECEIPT_SIGNING_KEY",
            "dev-only-change-me"
        )

        self.ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

        self.RATE_LIMIT_PER_MIN = int(
            os.getenv("RATE_LIMIT_PER_MIN", "20")
        )

        self.invite_codes = [
            code.strip()
            for code in os.getenv("INVITE_CODES", "").split(",")
            if code.strip()
        ]


settings = Settings()

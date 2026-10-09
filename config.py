"""Configuration loaded only when the CLI runs; credentials are never logged."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
PRODUCT_OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "2027届央国企校招汇总.xlsx"


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    database_path: Path = PROJECT_ROOT / "data" / "recruitment.sqlite3"
    attachments_dir: Path = PROJECT_ROOT / "data" / "attachments"
    output_path: Path = PRODUCT_OUTPUT_PATH
    fallback_models: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        primary_model = os.getenv("LLM_MODEL_PRIMARY", "").strip() or os.getenv("LLM_MODEL", "").strip()
        fallback_models = tuple(
            value for value in (
                os.getenv(f"LLM_MODEL_FALLBACK_{index}", "").strip()
                for index in range(1, 11)
            ) if value and value != primary_model
        )
        fallback_models = tuple(dict.fromkeys(fallback_models))
        values = {
            "api_key": os.getenv("DASHSCOPE_API_KEY", "").strip(),
            "base_url": os.getenv("LLM_BASE_URL", "").strip(),
            "model": primary_model,
            "fallback_models": fallback_models,
        }
        missing = [name for name in ("api_key", "base_url", "model") if not values[name]]
        if missing:
            raise ValueError("缺少配置：" + ", ".join(missing) + "。请检查环境变量或 .env。")
        return cls(**values)

"""Configuration loaded only when the CLI runs; credentials are never logged."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    database_path: Path = PROJECT_ROOT / "data" / "recruitment.sqlite3"
    attachments_dir: Path = PROJECT_ROOT / "data" / "attachments"
    output_path: Path = PROJECT_ROOT / "data" / "output" / "2027届央国企事业编招聘汇总.xlsx"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env")
        values = {
            "api_key": os.getenv("DASHSCOPE_API_KEY", "").strip(),
            "base_url": os.getenv("LLM_BASE_URL", "").strip(),
            "model": os.getenv("LLM_MODEL", "").strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError("缺少配置：" + ", ".join(missing) + "。请检查环境变量或 .env。")
        return cls(**values)

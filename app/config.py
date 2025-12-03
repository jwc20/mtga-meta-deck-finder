from pathlib import Path
import os
import logging
import logging.config
import os
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def find_project_root(marker=".git"):
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    return current.parent


log_file_path = Path(os.path.expanduser("~")) / ".seventeenlands" / "fake_seventeenlands.log"

project_root = find_project_root()
db_path = project_root / "database.db"
schema_path = project_root / "schema.sql"
template_path = project_root / "app/templates"

config_file_path = project_root / "config.yaml"

LOG_DIR = log_file_path / "logs"


class DailyFileHandler(logging.FileHandler):
    def __init__(self, log_dir: str = "logs", prefix: str = "app", encoding: str = "utf-8"):
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.current_date = None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._get_filepath()
        super().__init__(filepath, mode="a", encoding=encoding)

    def _get_filepath(self) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.current_date = date_str
        return str(self.log_dir / f"{self.prefix}_{date_str}.log")

    def emit(self, record: logging.LogRecord) -> None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        if date_str != self.current_date:
            self.close()
            self.baseFilename = self._get_filepath()
            self.stream = self._open()
        super().emit(record)


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(request_id)s",
            "rename_fields": {
                "levelname": "level",
                "asctime": "time",
            },
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "level": "DEBUG",
        },
        "file": {
            "()": "app.config.DailyFileHandler",
            "log_dir": "logs",
            "prefix": "app",
            "formatter": "json",
            "level": "DEBUG",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "uvicorn": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def generate_request_id() -> str:
    return str(uuid.uuid4())[:8]


def setup_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)

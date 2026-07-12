import logging
import sys
from datetime import datetime
from pathlib import Path
from contextvars import ContextVar

agent_id_ctx: ContextVar[str] = ContextVar("agent_id", default="-")
session_id_ctx: ContextVar[str] = ContextVar("session_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.agent_id = agent_id_ctx.get()
        record.session_id = session_id_ctx.get()
        return True


def setup_logging(app_name: str = "stock_research") -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / f"{app_name}_{datetime.now().strftime('%Y%m%d')}.log"

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - "
        "session=%(session_id)s agent=%(agent_id)s "
        "%(name)s - %(message)s"
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ContextFilter())

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()  # prevent duplicate logs
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

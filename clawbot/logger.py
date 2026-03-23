import json
import logging
import sys
from datetime import datetime, timezone

logger = logging.getLogger("clawbot")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra"):
            entry.update(record.extra)
        return json.dumps(entry)


def setup_logging(level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("clawbot")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
    root.propagate = False


def log_trade(event: str, **kwargs):
    extra = {"event": event, **kwargs}
    record = logger.makeRecord(
        "clawbot.trade", logging.INFO, "", 0, event, (), None
    )
    record.extra = extra
    logger.handle(record)

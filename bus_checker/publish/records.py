from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from bus_checker.config import Settings
from bus_checker.schema import PUBLICATIONS
from bus_checker.warehouse import quote_identifier, session

logger = logging.getLogger(__name__)


def record_publication(
    settings: Settings,
    publication_id: str,
    target: str,
    started: datetime,
    status: str,
    details: dict[str, Any],
    error: BaseException | None = None,
) -> None:
    columns = PUBLICATIONS.column_names
    values = {
        "publication_id": publication_id,
        "target": target,
        "started_at": started,
        "finished_at": datetime.now(UTC),
        "status": status,
        "details": json.dumps(details, default=str, sort_keys=True),
        "error_message": None if error is None else f"{type(error).__name__}: {error}"[:500],
    }
    try:
        with session(settings) as warehouse:
            names = ", ".join(quote_identifier(c) for c in columns)
            warehouse.execute(
                f"INSERT INTO {PUBLICATIONS.ref} ({names}) VALUES ({', '.join(':' + c for c in columns)})",
                values,
            )
    except Exception:
        logger.exception("Could not record publication %s", publication_id)

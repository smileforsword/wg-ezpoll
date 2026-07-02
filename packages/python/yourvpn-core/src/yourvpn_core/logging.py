from __future__ import annotations

import logging
import sys

from yourvpn_core.config import AppSettings


def configure_logging(settings: AppSettings, service: str) -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=f"%(asctime)s %(levelname)s service={service} %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )

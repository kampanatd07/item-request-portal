"""One logging setup for every entry point: the web app and the command-line
tools (e.g. `python -m app.unblock_ip`), so their audit lines look the same."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging() -> None:
    """App loggers (e.g. app.accounts, the Account admin log) at INFO, to
    stderr. basicConfig is a no-op if a handler is already installed, so a
    deploy can configure its own."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

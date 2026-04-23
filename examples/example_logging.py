from __future__ import annotations

import contextlib
import io
import logging
import sys
from datetime import datetime
from typing import Dict, Iterable, Iterator


class CompactFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        function_name = record.funcName
        return f"{timestamp} | {function_name} | {record.getMessage()}"


def get_logger(name: str = "bioformulations") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CompactFormatter())
    logger.addHandler(handler)
    return logger


def silence_framework_logging() -> None:
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("waitress").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("flask_cors").setLevel(logging.ERROR)


@contextlib.contextmanager
def suppress_startup_output() -> Iterator[None]:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
        yield


def log_server_initialized(logger: logging.Logger, server_name: str, host: str, port: int) -> None:
    logger.info("Client server for %s has been initiated at %s:%s", server_name, host, port)


def log_setup(logger: logging.Logger, stocks: Iterable[Dict[str, object]], component_bounds: Dict[str, Iterable[float]]) -> None:
    stock_summary = ", ".join(
        f"{stock['name']}->{stock['location']} ({stock['component']}={stock['concentration_mg_ml']} mg/mL)"
        for stock in stocks
    )
    bounds_summary = ", ".join(
        f"{component}=[{limits[0]}, {limits[1]}]"
        for component, limits in component_bounds.items()
    )
    logger.info("OT2 stocks loaded: %s", stock_summary)
    logger.info("Agent bounds configured: %s", bounds_summary)


def log_prepare_request(logger: logging.Logger, composition: Dict[str, float]) -> None:
    logger.info("Opentrons is asked to make samples with these concentrations %s", composition)


def log_transfer(logger: logging.Logger, sample_id: str, destination: str) -> None:
    logger.info("Xarm is moving the sample %s into the %s destination", sample_id, destination)


def log_measurement_triggered(logger: logging.Logger, sample_id: str) -> None:
    logger.info("Turbidity measurement triggered for sample %s", sample_id)


def log_measurement_result(logger: logging.Logger, sample_id: str, label: str) -> None:
    logger.info("Turbidity of the sample %s is %s", sample_id, label)


def log_agent_suggestion(logger: logging.Logger, composition: Dict[str, float]) -> None:
    logger.info("Agent suggests next samples to be %s", composition)

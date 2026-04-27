from __future__ import annotations

import contextlib
import io
import logging
import sys
from datetime import datetime
from typing import Dict, Iterable, Iterator, List


class CompactFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        return f"{timestamp} | {record.funcName} | {record.getMessage()}"


class _OnlyInfoFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == logging.INFO


@contextlib.contextmanager
def suppress_startup_output() -> Iterator[None]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def get_logger(name: str = "bioformulations") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.addFilter(_OnlyInfoFilter())
    handler.setFormatter(CompactFormatter())
    logger.addHandler(handler)
    return logger


def silence_framework_logging() -> None:
    logging.captureWarnings(True)
    logging.getLogger("py.warnings").handlers.clear()
    logging.getLogger("py.warnings").propagate = False
    for name in ("werkzeug", "waitress", "urllib3", "flask_cors", "zeroconf"):
        framework_logger = logging.getLogger(name)
        framework_logger.handlers.clear()
        framework_logger.propagate = False
        framework_logger.disabled = True


def log_server_initialized(logger: logging.Logger, server_name: str, host: str, port: int) -> None:
    logger.info("Client server for %s has been initiated at %s:%s", server_name, host, port)


def log_setup(
    logger: logging.Logger,
    stocks: Iterable[Dict[str, object]],
    component_bounds: Dict[str, Iterable[float]],
    temperature_bounds: Iterable[float],
    measurement_interval_s: float,
) -> None:
    logger.info(
        "OT2 stocks loaded: %s",
        ", ".join(
            f"{stock['name']}->{stock['location']} ({stock['component']}={stock['concentration_mg_ml']} mg/mL)"
            for stock in stocks
        ),
    )
    logger.info(
        "Agent bounds configured: %s",
        ", ".join(f"{component}=[{limits[0]}, {limits[1]}]" for component, limits in component_bounds.items()),
    )
    logger.info("Temperature sweep configured: range=%s interval=%s s", list(temperature_bounds), measurement_interval_s)


def log_prepare_request(logger: logging.Logger, composition: Dict[str, float]) -> None:
    logger.info("Opentrons is asked to make samples with these concentrations %s", composition)


def log_temperature_plan(logger: logging.Logger, sample_id: str, temperatures: List[float], measurement_interval_s: float) -> None:
    logger.info("Agent requested sample %s to be measured at temperatures %s with dwell %.1f s", sample_id, temperatures, measurement_interval_s)


def log_temperature_setpoint(logger: logging.Logger, sample_id: str, temperature_c: float, step_index: int, total_steps: int) -> None:
    logger.info("Opentrons sets sample %s to %.2f C for step %s/%s", sample_id, temperature_c, step_index + 1, total_steps)


def log_transfer(logger: logging.Logger, sample_id: str, destination: str) -> None:
    logger.info("Xarm is moving the sample %s into the %s destination", sample_id, destination)


def log_measurement_triggered(logger: logging.Logger, sample_id: str, temperature_c: float, measurement_interval_s: float) -> None:
    logger.info("Turbidity measurement triggered for sample %s at %.2f C after %.1f s", sample_id, temperature_c, measurement_interval_s)


def log_measurement_result(logger: logging.Logger, sample_id: str, label: str, temperature_c: float) -> None:
    logger.info("Turbidity of the sample %s at %.2f C is %s", sample_id, temperature_c, label)


def log_agent_suggestion(logger: logging.Logger, composition: Dict[str, float], temperatures: List[float]) -> None:
    logger.info("Agent suggests next sample composition %s with temperatures %s", composition, temperatures)

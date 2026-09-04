"""Privacy-safe OpenLLMetry bootstrap for the Loan API."""

import logging
import os
from collections.abc import MutableMapping
from typing import Any, Callable, TypeVar


LOGGER = logging.getLogger(__name__)
TRUE_VALUES = {"1", "true", "yes", "on"}
Function = TypeVar("Function", bound=Callable[..., Any])


def _is_enabled(environment: MutableMapping[str, str]) -> bool:
    return environment.get("OPENLLMETRY_ENABLED", "").strip().lower() in TRUE_VALUES


def _resource_attributes(environment: MutableMapping[str, str]) -> dict[str, str]:
    attributes = {}
    deployment_environment = environment.get("OTEL_DEPLOYMENT_ENVIRONMENT", "").strip()
    service_version = environment.get("APP_VERSION", "").strip()
    if deployment_environment:
        attributes["deployment.environment.name"] = deployment_environment
    if service_version:
        attributes["service.version"] = service_version
    return attributes


def _enforce_privacy(environment: MutableMapping[str, str]) -> None:
    environment["TRACELOOP_TRACE_CONTENT"] = "false"
    environment["TRACELOOP_TELEMETRY"] = "false"
    environment["TRACELOOP_METRICS_ENABLED"] = "false"
    environment["TRACELOOP_LOGGING_ENABLED"] = "false"


def trace_workflow(*, name: str) -> Callable[[Function], Function]:
    """Apply an OpenLLMetry workflow span only in configured runtimes."""

    def decorator(function: Function) -> Function:
        if not _is_enabled(os.environ) or not os.environ.get(
            "TRACELOOP_BASE_URL", ""
        ).strip():
            return function
        _enforce_privacy(os.environ)
        from traceloop.sdk.decorators import workflow

        return workflow(name=name)(function)

    return decorator


def trace_agent(*, name: str) -> Callable[[Function], Function]:
    """Apply an OpenLLMetry agent span only in configured runtimes."""

    def decorator(function: Function) -> Function:
        if not _is_enabled(os.environ) or not os.environ.get(
            "TRACELOOP_BASE_URL", ""
        ).strip():
            return function
        _enforce_privacy(os.environ)
        from traceloop.sdk.decorators import agent

        return agent(name=name)(function)

    return decorator


def initialize_observability(
    app: Any,
    *,
    environment: MutableMapping[str, str] | None = None,
    initializer: Callable[..., Any] | None = None,
    instrument_app: Callable[..., Any] | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Enable direct OTLP export without making observability a runtime dependency."""
    environment = environment if environment is not None else os.environ
    logger = logger or LOGGER

    if getattr(app.state, "openllmetry_initialized", False):
        return True
    if not _is_enabled(environment):
        return False

    # Loan documents and model responses may contain PII. These safeguards are
    # deliberately enforced instead of accepting operator-provided true values.
    _enforce_privacy(environment)

    api_endpoint = environment.get("TRACELOOP_BASE_URL", "").strip()
    if not api_endpoint:
        logger.warning(
            "OpenLLMetry is enabled but TRACELOOP_BASE_URL is missing; tracing remains disabled."
        )
        return False

    app_name = environment.get("OTEL_SERVICE_NAME", "loan-fastapi").strip() or "loan-fastapi"

    try:
        if initializer is None:
            from traceloop.sdk import Traceloop

            initializer = Traceloop.init
        initializer(
            app_name=app_name,
            api_endpoint=api_endpoint,
            telemetry_enabled=False,
            resource_attributes=_resource_attributes(environment),
        )
    except Exception as error:
        logger.warning(
            "OpenLLMetry initialization failed (%s); the Loan API will continue without tracing.",
            type(error).__name__,
        )
        return False

    try:
        if instrument_app is None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            instrument_app = FastAPIInstrumentor.instrument_app
        instrument_app(app, excluded_urls="token,docs,openapi.json")
    except Exception as error:
        logger.warning(
            "FastAPI tracing instrumentation failed (%s); SDK tracing remains active.",
            type(error).__name__,
        )

    app.state.openllmetry_initialized = True
    return True

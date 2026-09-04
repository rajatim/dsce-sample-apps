import importlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
if str(BACKEND_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIRECTORY))


class ObservabilityTest(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("observability", None)
        self.observability = importlib.import_module("observability")
        self.app = SimpleNamespace(state=SimpleNamespace())

    def test_disabled_by_default_does_not_initialize_or_instrument(self):
        initializer = Mock()
        instrument_app = Mock()

        enabled = self.observability.initialize_observability(
            self.app,
            environment={},
            initializer=initializer,
            instrument_app=instrument_app,
        )

        self.assertFalse(enabled)
        initializer.assert_not_called()
        instrument_app.assert_not_called()

    def test_enabled_configuration_forces_private_direct_otlp_export(self):
        environment = {
            "OPENLLMETRY_ENABLED": "true",
            "TRACELOOP_BASE_URL": "instana-agent.instana-agent:4317",
            "TRACELOOP_TRACE_CONTENT": "true",
            "TRACELOOP_TELEMETRY": "true",
            "OTEL_SERVICE_NAME": "loan-fastapi",
            "OTEL_DEPLOYMENT_ENVIRONMENT": "poc",
            "APP_VERSION": "abc1234",
        }
        initializer = Mock()
        instrument_app = Mock()

        enabled = self.observability.initialize_observability(
            self.app,
            environment=environment,
            initializer=initializer,
            instrument_app=instrument_app,
        )

        self.assertTrue(enabled)
        self.assertEqual(environment["TRACELOOP_TRACE_CONTENT"], "false")
        self.assertEqual(environment["TRACELOOP_TELEMETRY"], "false")
        self.assertEqual(environment["TRACELOOP_METRICS_ENABLED"], "false")
        self.assertEqual(environment["TRACELOOP_LOGGING_ENABLED"], "false")
        initializer.assert_called_once_with(
            app_name="loan-fastapi",
            api_endpoint="instana-agent.instana-agent:4317",
            telemetry_enabled=False,
            resource_attributes={
                "deployment.environment.name": "poc",
                "service.version": "abc1234",
            },
        )
        instrument_app.assert_called_once_with(
            self.app,
            excluded_urls="token,docs,openapi.json",
        )
        self.assertTrue(self.app.state.openllmetry_initialized)

    def test_enabled_without_endpoint_fails_closed(self):
        initializer = Mock()
        instrument_app = Mock()
        logger = Mock()

        enabled = self.observability.initialize_observability(
            self.app,
            environment={"OPENLLMETRY_ENABLED": "true"},
            initializer=initializer,
            instrument_app=instrument_app,
            logger=logger,
        )

        self.assertFalse(enabled)
        initializer.assert_not_called()
        instrument_app.assert_not_called()
        logger.warning.assert_called_once()

    def test_initialization_failure_does_not_expose_error_details(self):
        logger = Mock()
        initializer = Mock(side_effect=RuntimeError("secret endpoint and token"))

        enabled = self.observability.initialize_observability(
            self.app,
            environment={
                "OPENLLMETRY_ENABLED": "true",
                "TRACELOOP_BASE_URL": "private-endpoint:4317",
            },
            initializer=initializer,
            instrument_app=Mock(),
            logger=logger,
        )

        self.assertFalse(enabled)
        warning_text = " ".join(str(value) for value in logger.warning.call_args.args)
        self.assertNotIn("secret", warning_text)
        self.assertNotIn("private-endpoint", warning_text)

    def test_repeated_initialization_is_idempotent(self):
        environment = {
            "OPENLLMETRY_ENABLED": "true",
            "TRACELOOP_BASE_URL": "instana-agent.instana-agent:4317",
        }
        initializer = Mock()
        instrument_app = Mock()

        first = self.observability.initialize_observability(
            self.app,
            environment=environment,
            initializer=initializer,
            instrument_app=instrument_app,
        )
        second = self.observability.initialize_observability(
            self.app,
            environment=environment,
            initializer=initializer,
            instrument_app=instrument_app,
        )

        self.assertTrue(first)
        self.assertTrue(second)
        initializer.assert_called_once()
        instrument_app.assert_called_once()

    def test_disabled_span_decorators_are_identity_functions(self):
        original_environment = os.environ.get("OPENLLMETRY_ENABLED")
        os.environ["OPENLLMETRY_ENABLED"] = "false"

        def workflow_function():
            return "workflow"

        def agent_function():
            return "agent"

        try:
            self.assertIs(
                self.observability.trace_workflow(name="loan_preprocessing")(
                    workflow_function
                ),
                workflow_function,
            )
            self.assertIs(
                self.observability.trace_agent(name="loan_agent_workflow")(
                    agent_function
                ),
                agent_function,
            )
        finally:
            if original_environment is None:
                os.environ.pop("OPENLLMETRY_ENABLED", None)
            else:
                os.environ["OPENLLMETRY_ENABLED"] = original_environment

    @patch.dict(
        os.environ,
        {
            "OPENLLMETRY_ENABLED": "true",
            "TRACELOOP_BASE_URL": "test-only:4317",
        },
        clear=False,
    )
    def test_main_wires_observability_and_workflow_boundaries(self):
        sys.modules.pop("main", None)
        sys.modules.pop("utils.agents", None)
        with patch.object(
            self.observability, "initialize_observability"
        ) as initializer:
            main = importlib.import_module("main")

        initializer.assert_called_once_with(main.app)
        self.assertTrue(hasattr(main.process_application_in_background, "__wrapped__"))
        self.assertTrue(hasattr(main.invoke_agents, "__wrapped__"))


if __name__ == "__main__":
    unittest.main()

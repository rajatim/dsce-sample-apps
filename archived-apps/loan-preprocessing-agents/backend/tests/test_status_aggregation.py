import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from status_models import (
    DependencyStatus,
    EvidenceKind,
    StatusValue,
    SystemStatusResponse,
)
from services.status_aggregation import build_capabilities, build_overall


READY_CONTRACT = json.loads(
    (
        Path(__file__).parents[2]
        / "contracts"
        / "system-status-ready.json"
    ).read_text(encoding="utf-8")
)


def dependency(name: str, status: StatusValue) -> DependencyStatus:
    return DependencyStatus(
        id=name,
        label=name,
        status=status,
        evidence=EvidenceKind.LIVE_CHECK,
        message="test",
    )


def ready_dependencies() -> dict[str, DependencyStatus]:
    names = {
        "loan_api",
        "postgresql",
        "cos",
        "watsonx_ai",
        "wxo",
        "document_processing_agent",
        "document_validation_agent",
        "final_decision_agent",
        "openllmetry",
    }
    return {name: dependency(name, StatusValue.READY) for name in names}


class StatusAggregationTests(unittest.TestCase):
    def test_ready_copy_matches_the_approved_demo_contract(self):
        capabilities = build_capabilities(ready_dependencies())
        by_id = {item.id: item for item in capabilities}

        self.assertEqual(
            (by_id["submit_application"].label, by_id["submit_application"].message),
            (
                "Submit an application",
                "Online form and PDF upload are available.",
            ),
        )
        self.assertEqual(
            by_id["process_documents"].message,
            "Uploaded documents can be extracted and validated.",
        )
        self.assertEqual(
            by_id["generate_decision"].message,
            "Agent processing is available. Results may take 2–4 minutes.",
        )
        self.assertEqual(
            by_id["view_applications"].message,
            "Application history and processing details are available.",
        )

        overall = build_overall(capabilities)
        self.assertEqual(overall.title, "Demo ready")
        self.assertEqual(
            overall.message,
            "You can submit and review loan applications.",
        )
        self.assertEqual(
            {
                "overall": overall.model_dump(mode="json"),
                "capabilities": [
                    capability.model_dump(mode="json")
                    for capability in capabilities
                ],
            },
            {
                "overall": READY_CONTRACT["overall"],
                "capabilities": READY_CONTRACT["capabilities"],
            },
        )

    def test_limited_and_unavailable_overall_copy_matches_the_approved_demo_contract(self):
        limited_dependencies = ready_dependencies()
        limited_dependencies["wxo"] = dependency("wxo", StatusValue.LIMITED)
        limited = build_overall(build_capabilities(limited_dependencies))

        unavailable_dependencies = ready_dependencies()
        unavailable_dependencies["loan_api"] = dependency(
            "loan_api", StatusValue.UNAVAILABLE
        )
        unavailable_dependencies["postgresql"] = dependency(
            "postgresql", StatusValue.UNAVAILABLE
        )
        unavailable = build_overall(build_capabilities(unavailable_dependencies))

        self.assertEqual(
            (limited.title, limited.message),
            (
                "Some demo features are limited",
                "Check the details below before continuing.",
            ),
        )
        self.assertEqual(
            (unavailable.title, unavailable.message),
            (
                "The demo is currently unavailable",
                "Please try again later.",
            ),
        )

    def test_each_non_ready_capability_has_fixed_operation_specific_copy(self):
        cases = (
            (
                "submit_application",
                "loan_api",
                StatusValue.LIMITED,
                "You can still submit an application, but it may take longer than usual.",
            ),
            (
                "submit_application",
                "loan_api",
                StatusValue.UNAVAILABLE,
                "Application submission is unavailable. Please try again later.",
            ),
            (
                "submit_application",
                "loan_api",
                StatusValue.NOT_CONFIGURED,
                "Application submission is not configured for this demo.",
            ),
            (
                "process_documents",
                "document_processing_agent",
                StatusValue.LIMITED,
                "You can continue, but document processing may take longer than usual.",
            ),
            (
                "process_documents",
                "document_processing_agent",
                StatusValue.UNAVAILABLE,
                "Document processing is unavailable. Please try again later.",
            ),
            (
                "process_documents",
                "document_processing_agent",
                StatusValue.NOT_CONFIGURED,
                "Document processing is not configured for this demo.",
            ),
            (
                "generate_decision",
                "final_decision_agent",
                StatusValue.LIMITED,
                "You can continue, but a loan decision may take longer than usual.",
            ),
            (
                "generate_decision",
                "final_decision_agent",
                StatusValue.UNAVAILABLE,
                "Loan decisions are unavailable. Please try again later.",
            ),
            (
                "generate_decision",
                "final_decision_agent",
                StatusValue.NOT_CONFIGURED,
                "Loan decisions are not configured for this demo.",
            ),
            (
                "view_applications",
                "postgresql",
                StatusValue.LIMITED,
                "You can still view applications, but history may take longer to load.",
            ),
            (
                "view_applications",
                "postgresql",
                StatusValue.UNAVAILABLE,
                "Application history is unavailable. Please try again later.",
            ),
            (
                "view_applications",
                "postgresql",
                StatusValue.NOT_CONFIGURED,
                "Application history is not configured for this demo.",
            ),
        )

        for capability_id, dependency_id, status, expected_message in cases:
            with self.subTest(capability_id=capability_id, status=status):
                dependencies = ready_dependencies()
                dependencies[dependency_id] = dependency(dependency_id, status)

                capabilities = {
                    item.id: item for item in build_capabilities(dependencies)
                }
                capability = capabilities[capability_id]

                self.assertIs(capability.status, status)
                self.assertEqual(capability.message, expected_message)
                self.assertNotRegex(
                    capability.message.casefold(),
                    r"https?://|\b(postgresql|cos|watsonx|wxo|openllmetry)\b|"
                    r"document_(processing|validation)_agent|final_decision_agent",
                )

    def test_wxo_outage_limits_processing_but_keeps_history_ready(self):
        dependencies = ready_dependencies()
        dependencies["wxo"] = dependency("wxo", StatusValue.UNAVAILABLE)

        capabilities = {item.id: item for item in build_capabilities(dependencies)}

        self.assertIs(capabilities["view_applications"].status, StatusValue.READY)
        self.assertIs(capabilities["process_documents"].status, StatusValue.UNAVAILABLE)
        self.assertIs(capabilities["generate_decision"].status, StatusValue.UNAVAILABLE)

    def test_openllmetry_never_changes_capability_or_overall_status(self):
        dependencies = ready_dependencies()
        dependencies["openllmetry"] = dependency("openllmetry", StatusValue.UNAVAILABLE)

        capabilities = build_capabilities(dependencies)

        self.assertTrue(all(item.status is StatusValue.READY for item in capabilities))
        self.assertIs(build_overall(capabilities).status, StatusValue.READY)

    def test_missing_required_dependency_is_unknown_and_limits_capability(self):
        dependencies = ready_dependencies()
        del dependencies["wxo"]

        capabilities = {item.id: item for item in build_capabilities(dependencies)}

        self.assertIs(capabilities["process_documents"].status, StatusValue.LIMITED)

    def test_submit_and_view_unavailable_make_overall_unavailable(self):
        dependencies = ready_dependencies()
        dependencies["loan_api"] = dependency("loan_api", StatusValue.UNAVAILABLE)
        dependencies["postgresql"] = dependency("postgresql", StatusValue.UNAVAILABLE)

        capabilities = build_capabilities(dependencies)

        self.assertIs(build_overall(capabilities).status, StatusValue.UNAVAILABLE)

    def test_submit_and_view_not_configured_make_overall_unavailable(self):
        dependencies = ready_dependencies()
        dependencies["loan_api"] = dependency(
            "loan_api", StatusValue.NOT_CONFIGURED
        )

        capabilities = build_capabilities(dependencies)

        self.assertIs(build_overall(capabilities).status, StatusValue.UNAVAILABLE)

    def test_unavailable_submit_and_not_configured_view_make_overall_unavailable(
        self,
    ):
        dependencies = ready_dependencies()
        dependencies["loan_api"] = dependency(
            "loan_api", StatusValue.NOT_CONFIGURED
        )
        dependencies["cos"] = dependency("cos", StatusValue.UNAVAILABLE)

        capabilities = build_capabilities(dependencies)

        self.assertIs(build_overall(capabilities).status, StatusValue.UNAVAILABLE)

    def test_capability_status_precedence_is_unavailable_then_not_configured_then_limited(
        self,
    ):
        dependencies = ready_dependencies()
        dependencies["loan_api"] = dependency("loan_api", StatusValue.LIMITED)
        dependencies["postgresql"] = dependency(
            "postgresql", StatusValue.NOT_CONFIGURED
        )
        dependencies["cos"] = dependency("cos", StatusValue.UNAVAILABLE)

        capabilities = {
            item.id: item for item in build_capabilities(dependencies)
        }
        self.assertIs(
            capabilities["submit_application"].status,
            StatusValue.UNAVAILABLE,
        )

        dependencies["cos"] = dependency("cos", StatusValue.READY)
        capabilities = {
            item.id: item for item in build_capabilities(dependencies)
        }
        self.assertIs(
            capabilities["submit_application"].status,
            StatusValue.NOT_CONFIGURED,
        )

        dependencies["postgresql"] = dependency("postgresql", StatusValue.READY)
        capabilities = {
            item.id: item for item in build_capabilities(dependencies)
        }
        self.assertIs(
            capabilities["submit_application"].status,
            StatusValue.LIMITED,
        )

    def test_one_nonterminal_not_configured_capability_keeps_overall_limited(self):
        dependencies = ready_dependencies()
        dependencies["final_decision_agent"] = dependency(
            "final_decision_agent", StatusValue.NOT_CONFIGURED
        )

        capabilities = build_capabilities(dependencies)

        self.assertIs(build_overall(capabilities).status, StatusValue.LIMITED)

    def test_other_mixed_capability_state_is_limited(self):
        dependencies = ready_dependencies()
        dependencies["wxo"] = dependency("wxo", StatusValue.LIMITED)

        capabilities = build_capabilities(dependencies)

        self.assertIs(build_overall(capabilities).status, StatusValue.LIMITED)

    def test_checking_required_dependency_limits_capability(self):
        dependencies = ready_dependencies()
        dependencies["wxo"] = dependency("wxo", StatusValue.CHECKING)

        capabilities = {item.id: item for item in build_capabilities(dependencies)}

        self.assertIs(capabilities["process_documents"].status, StatusValue.LIMITED)

    def test_public_response_models_reject_extra_fields(self):
        with self.assertRaises(ValueError):
            SystemStatusResponse(
                overall={"status": "ready", "title": "Ready", "message": "ok"},
                checked_at=datetime.now(timezone.utc),
                stale_after_seconds=60,
                capabilities=[],
                dependencies=[],
                secret="must not leak",
            )


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timezone

from status_models import (
    DependencyStatus,
    EvidenceKind,
    StatusValue,
    SystemStatusResponse,
)
from services.status_aggregation import build_capabilities, build_overall


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

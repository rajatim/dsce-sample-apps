# Loan Demo Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 Loan POC 建立一般使用者看得懂、技術人員也能展開診斷的 `Demo status` 頁面，同時維持安全、低成本且不觸發 LLM 的健康檢查。

**Architecture:** FastAPI 保留淺層 `/healthz`，新增 PostgreSQL readiness `/readyz` 與公開但完全去敏感化的 `/system-status`。後端並行執行唯讀 dependency checks，使用 30 秒快取，並附加來自最新 500 筆 event bounded scan 的 timestamp-only Agent local history（不代表 freshness 或 availability），再由 React context 共用狀態，Carbon UI 呈現四個使用者 capability 與收合的技術細節。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLAlchemy、IBM COS SDK、IBM Cloud IAM／watsonx.ai／watsonx Orchestrate REST APIs、React 19、Vite、Vitest、IBM Carbon React。

**Spec:** `docs/superpowers/specs/2026-09-04-loan-demo-status-design.md`

## Global Constraints

- 不修改 Loan 審核業務邏輯、Agent prompt、模型或 Pass／Reject 判定。
- 狀態檢查不可做模型 inference、建立 WXO thread、執行 Agent、上傳或刪除 COS object。
- `/healthz` 只代表 FastAPI process 存活，不可呼叫任何外部 dependency。
- `/readyz` 只用 `SELECT 1` 檢查 PostgreSQL，不把 IBM Cloud 或 OpenLLMetry 納入 readiness。
- `/system-status` 視為公開 endpoint；不得回傳 API key、token、password、URL、CRN、project ID、instance ID、agent ID、bucket 名稱、PII、模型輸出或原始 exception。
- 外部檢查使用固定安全文案、短 timeout、30 秒快取、15 秒 force-refresh cooldown；90 秒以上資料標示 stale。
- OpenLLMetry 不影響使用者 capability 與 overall status。
- Desktop 與 mobile 導覽都必須有 `Demo status`，路由固定為 `/status`。
- 每個狀態必須同時顯示圖示、文字與說明，不可只靠顏色。
- 既有 `backend/loan_app.db` 與 `backend/logs.json` 是執行資料，不可加入任何 commit。
- IBM 官方唯讀 API 依據：COS `HEAD Bucket` <https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-at-iam>、watsonx.ai project metadata <https://ibm.github.io/watsonx-ai-python-sdk/core_api.html#projects>、WXO registered agents <https://developer.watson-orchestrate.ibm.com/apis/agents-v2/list-registered-agents>。

## File Map

### Backend

- Create `backend/status_models.py`: 狀態 enum 與公開 response schema，集中 allowlist 欄位。
- Create `backend/services/status_aggregation.py`: dependency → capability → overall 的純函式規則。
- Create `backend/repositories/status_activity.py`: 從既有 `agent_events` 讀取最近三個 Agent 的執行證據。
- Create `backend/services/status_checks.py`: PostgreSQL、COS、watsonx.ai、WXO、OpenLLMetry 的唯讀檢查。
- Create `backend/services/system_status.py`: 並行檢查、快取、cooldown、stale 與 response 組裝。
- Modify `backend/utils/cos_client.py`: 提供不吞錯誤的 `head_bucket()` 唯讀方法。
- Modify `backend/main.py`: 掛載 `/readyz` 與 `/system-status`，保持 `/healthz` 不變。
- Create backend tests matching each responsibility.

### Frontend

- Create `frontend/src/services/systemStatus.js`: 呼叫與驗證 `/system-status`。
- Create `frontend/src/contexts/SystemStatusContext.jsx`: 全 App 共用狀態、refresh 與相對時間。
- Create `frontend/src/contexts/useSystemStatus.js`: context hook。
- Create `frontend/src/components/SystemStatus/SystemStatus.jsx`: 狀態頁。
- Create `frontend/src/components/SystemStatus/SystemStatus.css`: responsive Carbon layout。
- Create `frontend/src/components/CapabilityNotice/CapabilityNotice.jsx`: 操作頁的單一最高嚴重度通知。
- Modify `frontend/src/App.jsx`: Provider、desktop/mobile navigation 與 `/status` route。
- Modify `LoanApplication.jsx` and `MyApplications.jsx`: 放置相對應通知。
- Create or modify frontend tests for data, routing, interaction, accessibility and mobile behavior.

### Documentation

- Modify `backend/README.md`: 說明三個 endpoints、status 設定與本地驗證。
- Modify `frontend/README.md`: 說明 `/status`、API proxy 與測試方式。

---

### Task 1: Define the public status contract and pure aggregation rules

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/backend/status_models.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/services/status_aggregation.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_status_aggregation.py`

**Interfaces:**
- Produces: `StatusValue`, `EvidenceKind`, `DependencyStatus`, `CapabilityStatus`, `OverallStatus`, `SystemStatusResponse`.
- Produces: `build_capabilities(dependencies: Mapping[str, DependencyStatus]) -> list[CapabilityStatus]`.
- Produces: `build_overall(capabilities: Sequence[CapabilityStatus]) -> OverallStatus`.
- Consumes: no network, database or FastAPI objects; these functions stay deterministic.

- [ ] **Step 1: Write failing tests for dependency-to-capability mapping**

```python
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
```

- [ ] **Step 2: Run the aggregation tests and confirm RED**

Run:

```bash
cd archived-apps/loan-preprocessing-agents/backend
uv run python -m unittest tests.test_status_aggregation -v
```

Expected: import failure for `status_models` or `services.status_aggregation`.

- [ ] **Step 3: Add strict public response models**

Implement the following shape in `status_models.py`; `extra="forbid"` prevents accidental secret fields from leaking into the public contract:

```python
from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict


class StatusValue(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    CHECKING = "checking"
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"


class EvidenceKind(StrEnum):
    LIVE_CHECK = "live_check"
    CONFIGURED = "configured"
    RECENT_EXECUTION = "recent_execution"
    NOT_VERIFIED = "not_verified"


class PublicStatusModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DependencyStatus(PublicStatusModel):
    id: str
    label: str
    status: StatusValue
    evidence: EvidenceKind
    message: str
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None


class CapabilityStatus(PublicStatusModel):
    id: str
    label: str
    status: StatusValue
    message: str


class OverallStatus(PublicStatusModel):
    status: StatusValue
    title: str
    message: str


class SystemStatusResponse(PublicStatusModel):
    overall: OverallStatus
    checked_at: datetime
    stale_after_seconds: int
    stale: bool = False
    capabilities: list[CapabilityStatus]
    dependencies: list[DependencyStatus]
```

- [ ] **Step 4: Implement fixed capability maps and overall rules**

In `status_aggregation.py`, define exact dependency sets and fixed copy:

```python
CAPABILITY_DEPENDENCIES = {
    "submit_application": ("loan_api", "postgresql", "cos"),
    "process_documents": (
        "cos", "watsonx_ai", "wxo", "document_processing_agent",
        "document_validation_agent",
    ),
    "generate_decision": (
        "cos", "watsonx_ai", "wxo", "document_processing_agent",
        "document_validation_agent", "final_decision_agent",
    ),
    "view_applications": ("loan_api", "postgresql"),
}
```

Rules:

- Any required `unavailable` or `not_configured` makes that capability `unavailable`.
- Otherwise any required `limited` or `unknown` makes it `limited`.
- Otherwise all requirements are `ready` and capability is `ready`.
- Overall is `ready` only when all four capabilities are ready.
- Overall is `unavailable` when both `submit_application` and `view_applications` are unavailable.
- Every other mixed state is `limited`.
- All titles and messages come from constants, never exceptions.

- [ ] **Step 5: Run focused tests and the existing backend suite**

```bash
uv run python -m unittest tests.test_status_aggregation -v
uv run python -m unittest discover -s tests -v
```

Expected: both commands exit 0 with no failures.

- [ ] **Step 6: Commit Task 1**

```bash
git add archived-apps/loan-preprocessing-agents/backend/status_models.py \
  archived-apps/loan-preprocessing-agents/backend/services/status_aggregation.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_status_aggregation.py
git commit -m "feat: define loan demo status model"
```

### Task 2: Derive privacy-safe recent Agent activity from existing events

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/backend/repositories/status_activity.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_status_activity.py`

**Interfaces:**
- Consumes: existing `models.AgentEvent`, `database.SessionLocal`, invocation messages already stored by `utils.agents.invoke_agents`.
- Produces: `get_recent_agent_activity(session_factory=SessionLocal, limit: int = 500) -> dict[str, AgentActivity]`.
- Produces: `AgentActivity(agent_key: str, last_success_at: datetime | None, last_failure_at: datetime | None)`.

- [ ] **Step 1: Write failing repository tests**

Create SQLite-backed tests following `tests/test_agent_event_repository.py` and cover:

```python
def test_correlates_responses_with_the_latest_agent_invocation(self):
    append("app-1", "invoke_agent", {"message": "Invoking Document Processor Agent"})
    append("app-1", "agent_response", {"message": "extraction complete"})
    append("app-1", "invoke_agent", {"message": "Invoking Document Validator Agent"})
    append("app-1", "agent_response", {"message": "I have encountered an error. Please try again."})

    activity = get_recent_agent_activity(self.session_factory)

    self.assertIsNotNone(activity["document_processing_agent"].last_success_at)
    self.assertIsNotNone(activity["document_validation_agent"].last_failure_at)


def test_returns_timestamps_only_and_never_payload_content(self):
    activity = get_recent_agent_activity(self.session_factory)
    self.assertFalse(hasattr(activity["final_decision_agent"], "payload"))
```

- [ ] **Step 2: Run the repository test and confirm RED**

```bash
uv run python -m unittest tests.test_status_activity -v
```

Expected: import failure for `repositories.status_activity`.

- [ ] **Step 3: Implement bounded event correlation**

Implementation requirements:

- Query at most 500 newest events, then process them oldest-to-newest.
- Track current agent separately for each `external_application_id`.
- Recognize only the fixed invocation markers `Document Processor`, `Document Validator`, and `Final Decision`.
- Treat an `agent_response` containing the existing retryable phrases as failure; other non-empty responses are success.
- Never return event payload, application ID, applicant data, response body or failure message.
- An application without an invocation marker contributes no Agent activity.

Use this immutable return type:

```python
@dataclass(frozen=True)
class AgentActivity:
    agent_key: str
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
```

- [ ] **Step 4: Run focused and repository suites**

```bash
uv run python -m unittest tests.test_status_activity tests.test_agent_event_repository -v
```

Expected: exit 0 with no failures.

- [ ] **Step 5: Commit Task 2**

```bash
git add archived-apps/loan-preprocessing-agents/backend/repositories/status_activity.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_status_activity.py
git commit -m "feat: summarize recent loan agent activity"
```

### Task 3: Implement low-cost, read-only dependency checks

**Files:**
- Modify: `archived-apps/loan-preprocessing-agents/backend/utils/cos_client.py:15-67`
- Create: `archived-apps/loan-preprocessing-agents/backend/services/status_checks.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_status_checks.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_cos_status_check.py`

**Interfaces:**
- Produces: `COSClient.head_bucket(bucket_name: str) -> None` which raises on failure.
- Produces: `check_postgresql(session_factory, checked_at) -> DependencyStatus`.
- Produces: `check_cos(client_factory, bucket_name, checked_at) -> DependencyStatus`.
- Produces: `check_watsonx(environment, http, checked_at) -> DependencyStatus`.
- Produces: `check_wxo(environment, http, checked_at) -> list[DependencyStatus]`.
- Produces: `check_openllmetry(environment, initialized, checked_at) -> DependencyStatus`.

- [ ] **Step 1: Write failing COS tests**

```python
def test_head_bucket_is_read_only_and_does_not_swallow_errors():
    sdk = Mock()
    client = object.__new__(COSClient)
    client._cos = sdk

    client.head_bucket("loan-demo")

    sdk.head_bucket.assert_called_once_with(Bucket="loan-demo")


def test_head_bucket_propagates_sdk_failure():
    sdk = Mock()
    sdk.head_bucket.side_effect = RuntimeError("secret provider response")
    client = object.__new__(COSClient)
    client._cos = sdk

    with self.assertRaises(RuntimeError):
        client.head_bucket("loan-demo")
```

- [ ] **Step 2: Write failing dependency check tests**

Tests must verify:

- Missing variables produce `not_configured`／`not_verified` and a fixed public message.
- PostgreSQL executes exactly `SELECT 1` and performs no write.
- COS calls only `head_bucket`.
- watsonx.ai obtains an IAM token and performs `GET {WATSONX_URL}/v2/projects/{WATSONX_PROJECT_ID}` with connect/read timeout `(2, 3)`.
- WXO performs `GET {instance_root}/v2/orchestrate/agents` and compares the three configured IDs without creating threads or runs.
- HTTP 401, 403, 404, 429, 5xx and timeout map to fixed statuses without provider response text.
- OpenLLMetry disabled is `not_configured`; enabled and initialized is `ready`; enabled but not initialized is `limited`.

- [ ] **Step 3: Run the checks and confirm RED**

```bash
uv run python -m unittest tests.test_cos_status_check tests.test_status_checks -v
```

Expected: missing `head_bucket` and `services.status_checks` failures.

- [ ] **Step 4: Add the explicit COS metadata method**

```python
def head_bucket(self, bucket_name: str) -> None:
    """Verify read-only bucket metadata access; propagate failures to the caller."""
    self._cos.head_bucket(Bucket=bucket_name)
```

Do not modify existing upload, download or listing behavior.

- [ ] **Step 5: Implement IBM IAM and watsonx.ai checks**

In `status_checks.py`:

- POST to `https://iam.cloud.ibm.com/identity/token` with form data and timeout `(2, 3)`.
- Keep bearer token local to the function; never place it in a result, log or exception message.
- GET the project metadata at `{WATSONX_URL}/v2/projects/{WATSONX_PROJECT_ID}` with `Authorization: Bearer ...` and timeout `(2, 3)`.
- Treat HTTP 200 as `ready/live_check`.
- Map missing configuration to `not_configured/not_verified` and request failures to `unavailable/live_check` using fixed copy.
- Log only service label plus exception class at warning level.

- [ ] **Step 6: Implement WXO registered-agent lookup**

Resolve the instance root with these exact rules:

```python
if WXO_SERVICE_INSTANCE_URL:
    root = WXO_SERVICE_INSTANCE_URL.rstrip("/")
elif WXO_INSTANCE_CLOUD == "ibmcloud":
    root = (
        f"https://api.{WXO_INSTANCE_CLOUD_REGION}.watson-orchestrate.cloud.ibm.com"
        f"/instances/{WXO_INSTANCE_ID}"
    )
else:
    root = f"https://api.dl.watson-orchestrate.ibm.com/instances/{WXO_INSTANCE_ID}"
```

Then:

- Obtain a token using `WXO_API_KEY`.
- GET `{root}/v2/orchestrate/agents` with repeated `ids` query parameters for the three configured Agent IDs.
- Mark WXO `ready` only on HTTP 200.
- Mark each Agent `ready` only when its ID exists in the returned registered-agent collection.
- Do not expose any returned ID or response body.

- [ ] **Step 7: Run focused and full backend tests**

```bash
uv run python -m unittest tests.test_cos_status_check tests.test_status_checks -v
uv run python -m unittest discover -s tests -v
```

Expected: both commands exit 0 with no failures and mocks show no inference, upload, thread or run call.

- [ ] **Step 8: Commit Task 3**

```bash
git add archived-apps/loan-preprocessing-agents/backend/utils/cos_client.py \
  archived-apps/loan-preprocessing-agents/backend/services/status_checks.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_cos_status_check.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_status_checks.py
git commit -m "feat: add read-only loan dependency checks"
```

### Task 4: Add cached system-status service and FastAPI endpoints

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/backend/services/system_status.py`
- Modify: `archived-apps/loan-preprocessing-agents/backend/main.py:17-70`
- Modify: `archived-apps/loan-preprocessing-agents/backend/tests/test_startup.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_system_status_service.py`
- Create: `archived-apps/loan-preprocessing-agents/backend/tests/test_status_endpoints.py`

**Interfaces:**
- Consumes: Task 1 aggregation, Task 2 activity, Task 3 check functions.
- Produces: `SystemStatusService.get_status(force_refresh: bool = False) -> SystemStatusResponse`.
- Produces: `GET /readyz` and `GET /system-status?refresh=false`.

- [ ] **Step 1: Write failing cache and orchestration tests**

Cover these exact behaviors:

```python
def test_reuses_cached_result_for_thirty_seconds(self):
    first = service.get_status()
    second = service.get_status()
    self.assertEqual(first.checked_at, second.checked_at)
    self.assertEqual(checks.call_count, 1)


def test_force_refresh_is_throttled_for_fifteen_seconds(self):
    first = service.get_status(force_refresh=True)
    clock.advance(seconds=10)
    second = service.get_status(force_refresh=True)
    self.assertEqual(second.checked_at, first.checked_at)


def test_one_timed_out_check_does_not_remove_other_results(self):
    result = service_with_timed_out_wxo.get_status()
    by_id = {item.id: item for item in result.dependencies}
    self.assertIs(by_id["postgresql"].status, StatusValue.READY)
    self.assertIs(by_id["wxo"].status, StatusValue.UNKNOWN)
```

Also assert that recent Agent timestamps are attached only to the corresponding Agent dependency and never change a failed live check into `ready`.

- [ ] **Step 2: Write failing endpoint tests**

Tests must verify:

- `/healthz` still returns exactly `200 {"status":"ok"}` when every dependency function raises.
- `/readyz` returns 200 for successful `SELECT 1` and 503 with only `{"status":"not_ready"}` on database failure.
- `/system-status` is accessible without Authorization.
- `/system-status` response validates against `SystemStatusResponse`.
- Serialized JSON does not contain supplied fake secrets, URLs, IDs or raw exception text.
- `refresh=true` calls `get_status(force_refresh=True)`.

- [ ] **Step 3: Run endpoint and service tests and confirm RED**

```bash
uv run python -m unittest tests.test_system_status_service tests.test_status_endpoints -v
```

Expected: missing service and route failures.

- [ ] **Step 4: Implement bounded parallel checks and cache**

`SystemStatusService` requirements:

- Constructor accepts clock, dependency callables and timeout/cache values for deterministic tests.
- Defaults: cache TTL 30 seconds, force-refresh cooldown 15 seconds, stale threshold 90 seconds, total check budget 5 seconds.
- Use `ThreadPoolExecutor` plus `concurrent.futures.wait`; cancel unfinished futures and call `shutdown(wait=False, cancel_futures=True)`.
- Each timed-out or failed check creates a fixed `unknown` or `unavailable` result without `str(exception)`.
- Protect refresh with `threading.Lock` so concurrent public requests share one refresh.
- Return dependencies in a stable display order.
- Attach `AgentActivity` timestamps after live WXO checks.
- Build capabilities and overall only through Task 1 pure functions.

- [ ] **Step 5: Add endpoints without changing business routes**

Use response models and safe error bodies:

```python
@app.get("/readyz", include_in_schema=False)
def readiness():
    if system_status_service.database_is_ready():
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not_ready"})


@app.get("/system-status", response_model=SystemStatusResponse)
def system_status(refresh: bool = False):
    return system_status_service.get_status(force_refresh=refresh)
```

Instantiate the service only after `initialize_observability(app)` so it can read `app.state.openllmetry_initialized`. Do not add authentication dependency.

- [ ] **Step 6: Run focused and full backend tests**

```bash
uv run python -m unittest tests.test_startup tests.test_system_status_service tests.test_status_endpoints -v
uv run python -m unittest discover -s tests -v
```

Expected: all tests pass; `/healthz` exact response remains unchanged.

- [ ] **Step 7: Commit Task 4**

```bash
git add archived-apps/loan-preprocessing-agents/backend/services/system_status.py \
  archived-apps/loan-preprocessing-agents/backend/main.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_startup.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_system_status_service.py \
  archived-apps/loan-preprocessing-agents/backend/tests/test_status_endpoints.py
git commit -m "feat: expose cached loan demo status"
```

### Task 5: Create the shared React status data layer

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/services/systemStatus.js`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/services/systemStatus.test.js`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/contexts/SystemStatusContext.jsx`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/contexts/useSystemStatus.js`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/contexts/SystemStatusContext.test.jsx`

**Interfaces:**
- Produces: `fetchSystemStatus({ refresh = false, signal } = {}) -> Promise<SystemStatusPayload>`.
- Produces context value `{ status, isLoading, isRefreshing, error, refresh, checkedAtLabel }`.
- Consumes: existing `authFetch` and `buildApiUrl`; the endpoint itself remains public.

- [ ] **Step 1: Write failing service tests**

```javascript
it('requests the public status endpoint without refresh by default', async () => {
  authFetchMock.mockResolvedValue(jsonResponse(validStatus));
  await fetchSystemStatus();
  expect(authFetchMock).toHaveBeenCalledWith(
    'http://127.0.0.1:8000/system-status',
    expect.objectContaining({ signal: undefined })
  );
});

it('uses refresh=true only for a manual refresh', async () => {
  authFetchMock.mockResolvedValue(jsonResponse(validStatus));
  await fetchSystemStatus({ refresh: true });
  expect(authFetchMock.mock.calls[0][0]).toContain('/system-status?refresh=true');
});
```

Also test non-2xx and malformed payloads produce one safe UI error, not raw server text.

- [ ] **Step 2: Write failing context tests**

Test initial loading, successful load, AbortController cleanup, manual refresh, duplicate-refresh suppression, and a ticking relative label without repeated screen-reader announcements.

- [ ] **Step 3: Run focused frontend tests and confirm RED**

```bash
cd archived-apps/loan-preprocessing-agents/frontend
npm test -- src/services/systemStatus.test.js src/contexts/SystemStatusContext.test.jsx
```

Expected: missing modules.

- [ ] **Step 4: Implement strict client-side payload checks**

`systemStatus.js` must accept only known status values and array-shaped `capabilities`／`dependencies`. It must throw `new Error('Demo status is currently unavailable.')` for malformed or failed responses and must never display the response body.

- [ ] **Step 5: Implement one shared provider**

Provider behavior:

- Fetch once when mounted.
- Keep the last successful payload while manual refresh runs.
- Suppress a second refresh while one is in flight.
- Abort in-flight request on unmount.
- Recompute the visual relative time every 30 seconds without fetching the backend again.
- Expose `checkedAtLabel` such as `Checked just now`, `Checked 2 minutes ago`, or `Status data is out of date`.

- [ ] **Step 6: Run tests, lint and build**

```bash
npm test -- src/services/systemStatus.test.js src/contexts/SystemStatusContext.test.jsx
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 5**

```bash
git add archived-apps/loan-preprocessing-agents/frontend/src/services/systemStatus.js \
  archived-apps/loan-preprocessing-agents/frontend/src/services/systemStatus.test.js \
  archived-apps/loan-preprocessing-agents/frontend/src/contexts/SystemStatusContext.jsx \
  archived-apps/loan-preprocessing-agents/frontend/src/contexts/useSystemStatus.js \
  archived-apps/loan-preprocessing-agents/frontend/src/contexts/SystemStatusContext.test.jsx
git commit -m "feat: share loan demo status in the frontend"
```

### Task 6: Build the responsive, user-first Demo status page

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/components/SystemStatus/SystemStatus.jsx`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/components/SystemStatus/SystemStatus.css`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/components/SystemStatus/SystemStatus.test.jsx`
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/App.jsx:1-98`
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/App.test.jsx`

**Interfaces:**
- Consumes: Task 5 `useSystemStatus()`.
- Produces: `/status` page and matching desktop/mobile links.

- [ ] **Step 1: Write failing page tests**

Cover:

- First layer shows exactly four capability cards and no raw IDs or URLs.
- `Technical details` is collapsed initially.
- Keyboard activation expands the details.
- Status uses visible words plus icons, not color alone.
- Refresh shows inline loading while preserving current cards.
- API error shows `Status unavailable` and a Retry button without blanking navigation.
- Stale payload displays out-of-date copy.
- Technical details marks OpenLLMetry as not affecting demo availability.

- [ ] **Step 2: Extend App route/navigation tests before implementation**

Add assertions that desktop and mobile both expose `Demo status`, the mobile link closes the drawer, and `/status` renders the page.

- [ ] **Step 3: Run page and App tests and confirm RED**

```bash
npm test -- src/components/SystemStatus/SystemStatus.test.jsx src/App.test.jsx
```

Expected: missing component, link and route failures.

- [ ] **Step 4: Implement Carbon UI hierarchy**

Use existing Carbon components: `Button`, `InlineLoading`, `Tag`, `Accordion`, `AccordionItem`, and icons for success, warning, error and unknown. Required visible hierarchy:

1. `Demo status` title and Refresh.
2. Overall status title, actionable message and checked time.
3. `What you can do now` with four capabilities.
4. One collapsed `Technical details` accordion.

Do not create gauges, charts, percentages, uptime history or a dense desktop table.

- [ ] **Step 5: Implement responsive and accessible styling**

CSS requirements:

- Use Carbon spacing and neutral surfaces already present in the app.
- Desktop: two-column capability grid; mobile below 672px: one column.
- Refresh has at least 44px clickable height and never escapes viewport.
- Text wraps; no horizontal scroll at 320px viewport.
- Technical details use stacked rows on mobile.
- Only the completed refresh summary uses `aria-live="polite"`; ticking relative time has no live region.
- Focus indicators remain visible.

- [ ] **Step 6: Wire Provider, route and both navigation modes**

Wrap the app content with `SystemStatusProvider`, add `SystemStatus` at `/status`, and add `Demo status` after `Loan Calculator` in desktop and mobile navigation. Keep existing redirects unchanged.

- [ ] **Step 7: Run focused tests, all frontend tests, lint and build**

```bash
npm test -- src/components/SystemStatus/SystemStatus.test.jsx src/App.test.jsx
npm test
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 8: Commit Task 6**

```bash
git add archived-apps/loan-preprocessing-agents/frontend/src/components/SystemStatus \
  archived-apps/loan-preprocessing-agents/frontend/src/App.jsx \
  archived-apps/loan-preprocessing-agents/frontend/src/App.test.jsx
git commit -m "feat: add responsive loan demo status page"
```

### Task 7: Surface only actionable capability notices in user flows

**Files:**
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/components/CapabilityNotice/CapabilityNotice.jsx`
- Create: `archived-apps/loan-preprocessing-agents/frontend/src/components/CapabilityNotice/CapabilityNotice.test.jsx`
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/components/LoanApplication/LoanApplication.jsx:1-100` and the top-level rendered content.
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/components/LoanApplication/LoanApplication.test.jsx`
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/components/MyApplications/MyApplications.jsx:1-90` and the top-level rendered content.
- Modify: `archived-apps/loan-preprocessing-agents/frontend/src/components/MyApplications/MyApplications.test.jsx`

**Interfaces:**
- Consumes: `useSystemStatus()` and capability IDs from Task 1.
- Produces: `<CapabilityNotice capabilityIds={[...]} />`.

- [ ] **Step 1: Write failing notice tests**

```javascript
it('renders nothing when all requested capabilities are ready', () => {
  mockCapabilities([{ id: 'submit_application', status: 'ready' }]);
  const { container } = render(
    <CapabilityNotice capabilityIds={['submit_application']} />
  );
  expect(container).toBeEmptyDOMElement();
});

it('shows only the highest-impact notice', () => {
  mockCapabilities([
    { id: 'submit_application', status: 'limited', message: 'Submission may be delayed.' },
    { id: 'process_documents', status: 'unavailable', message: 'Document processing is unavailable.' },
  ]);
  render(<CapabilityNotice capabilityIds={['submit_application', 'process_documents']} />);
  expect(screen.getByText('Document processing is unavailable.')).toBeVisible();
  expect(screen.queryByText('Submission may be delayed.')).not.toBeInTheDocument();
});
```

Also verify `unknown`, initial loading and stale-only states do not produce an outage notification.

- [ ] **Step 2: Add failing integration assertions**

- Apply page requests one notice for `submit_application`, `process_documents`, and `generate_decision`.
- My Applications requests one notice for `view_applications`.
- Existing preset, submit, polling and table tests remain unchanged in meaning.

- [ ] **Step 3: Run focused tests and confirm RED**

```bash
npm test -- src/components/CapabilityNotice/CapabilityNotice.test.jsx \
  src/components/LoanApplication/LoanApplication.test.jsx \
  src/components/MyApplications/MyApplications.test.jsx
```

Expected: missing component or missing notification assertions.

- [ ] **Step 4: Implement severity selection and safe Carbon notification**

Use severity order `unavailable > not_configured > limited`; render one `InlineNotification` with `kind="error"` for unavailable/not configured and `kind="warning"` for limited. Copy comes only from the status response allowlist. Include a `View demo status` link to `/status`.

- [ ] **Step 5: Place notices without changing forms or processing behavior**

- Place the Apply notice below the page heading and before method selection／form content.
- Place the My Applications notice below the heading and before the table/loading/error region.
- Do not disable form fields or buttons in this task; status information is advisory because `unknown` does not prove outage.

- [ ] **Step 6: Run focused and full frontend verification**

```bash
npm test -- src/components/CapabilityNotice/CapabilityNotice.test.jsx \
  src/components/LoanApplication/LoanApplication.test.jsx \
  src/components/MyApplications/MyApplications.test.jsx
npm test
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 7**

```bash
git add archived-apps/loan-preprocessing-agents/frontend/src/components/CapabilityNotice \
  archived-apps/loan-preprocessing-agents/frontend/src/components/LoanApplication/LoanApplication.jsx \
  archived-apps/loan-preprocessing-agents/frontend/src/components/LoanApplication/LoanApplication.test.jsx \
  archived-apps/loan-preprocessing-agents/frontend/src/components/MyApplications/MyApplications.jsx \
  archived-apps/loan-preprocessing-agents/frontend/src/components/MyApplications/MyApplications.test.jsx
git commit -m "feat: show actionable loan capability notices"
```

### Task 8: Document, verify locally, and prepare a deployment handoff

**Files:**
- Modify: `archived-apps/loan-preprocessing-agents/backend/README.md:19-40,154-end`
- Modify: `archived-apps/loan-preprocessing-agents/frontend/README.md`
- Modify: `docs/superpowers/plans/2026-09-04-loan-demo-status.md` only to check completed boxes and record deviations discovered during execution.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: reproducible local SIT evidence and a safe OpenShift handoff; this task does not mutate `itz-pl4yvb`.

- [x] **Step 1: Add backend operating documentation**

Document:

- `/healthz`: liveness only.
- `/readyz`: PostgreSQL readiness only.
- `/system-status`: public, sanitized, cached status.
- Default cache 30s, refresh cooldown 15s, stale threshold 90s, total check budget 5s.
- IBM calls are read-only: COS HEAD bucket, watsonx project GET, WXO agents GET.
- OpenLLMetry never affects overall availability.
- `curl` examples must redirect bodies to a temporary file or parse only allowlisted status fields; do not print credentials or internal configuration.

- [x] **Step 2: Add frontend documentation**

Document `/status`, desktop/mobile entry points, local API proxy behavior, and the commands `npm test`, `npm run lint`, `npm run build`.

- [x] **Step 3: Run the complete automated verification from clean processes**

Backend:

```bash
cd archived-apps/loan-preprocessing-agents/backend
uv sync --locked
uv run python -m unittest discover -s tests -v
```

Frontend:

```bash
cd ../frontend
npm ci
npm test
npm run lint
npm run build
```

Expected: every command exits 0; no test reaches real IBM Cloud.

- [x] **Step 4: Run local SIT with existing protected environment values**

Start FastAPI and Vite using the existing secret-loading procedure, then verify only public fields:

```bash
curl --fail --silent http://127.0.0.1:8000/healthz | jq -e '.status == "ok"'
curl --fail --silent http://127.0.0.1:8000/readyz | jq -e '.status == "ready"'
curl --fail --silent http://127.0.0.1:8000/system-status \
  | jq -e '
      (.overall.status | IN("ready", "limited", "unavailable", "unknown")) and
      (.capabilities | length == 4) and
      ([.dependencies[].id] | index("postgresql") != null)
    '
```

Do not print the complete dependency JSON during shared-screen validation.

- [x] **Step 5: Perform browser acceptance at desktop and mobile widths**

Verify:

- `/status` loads at 1440px, 768px, 390px and 320px.
- All four capabilities, Refresh, Retry and mobile navigation remain reachable.
- Technical details start collapsed and work by keyboard.
- Simulated partial failures preserve usable capabilities.
- Apply and My Applications show no green success banner during normal operation.
- No secret, ID, endpoint, PII or raw provider message appears in DOM or network response.

- [x] **Step 6: Record the OpenShift deployment gate**

Before changing `itz-pl4yvb`, require a separate explicit deployment approval and complete these read-only checks:

```bash
kubectl config current-context
kubectl auth whoami
kubectl get deployment,service,route -n dsce-loan-poc
kubectl get deployment loan-fastapi -n dsce-loan-poc -o yaml \
  | yq '.spec.template.spec.containers[].readinessProbe'
```

Expected namespace: `dsce-loan-poc`. If the live Deployment name differs from `loan-fastapi`, stop and update the deployment procedure document with the observed name before any mutation. The deployment execution must preserve `/healthz` as liveness and point readiness to `/readyz`; rollback must use the existing prior image digest rather than rebuilding an old tag.

- [x] **Step 7: Confirm the worktree contains no runtime files or secrets**

```bash
git status --short
git diff --check
git diff --cached --check
git diff --name-only 1dd6ca2..HEAD \
  | rg '(^|/)(loan_app\.db|logs\.json)$|(^|/)\.env($|\.)' \
  && exit 1 || true
git diff 1dd6ca2..HEAD | rg '(API_KEY|APIKEY|PASSWORD|Bearer )[=: ]+[A-Za-z0-9_-]{12,}' && exit 1 || true
```

Expected: the two known runtime files may remain modified locally, but they are absent from all feature commits and diffs selected for handoff.

- [x] **Step 8: Commit documentation**

```bash
git add archived-apps/loan-preprocessing-agents/backend/README.md \
  archived-apps/loan-preprocessing-agents/frontend/README.md \
  docs/superpowers/plans/2026-09-04-loan-demo-status.md
git commit -m "docs: describe loan demo status operations"
```

Task 8 execution deviations (2026-09-05):

- The backend discovery suite completed with 175 passing tests and two guarded
  PostgreSQL integration tests skipped because `TEST_DATABASE_URL` was
  deliberately absent from the clean automated-test process. Local SIT then
  exercised `/readyz` against the approved loopback PostgreSQL service.
- Vite 7 rejected the attempted `--envDir` launch option before starting. The
  successful launch instead read only `VITE_API_URL` from the existing
  protected `.env.local`; no secret or complete environment was printed.
- Browser tooling did not expose a response-body network capture. The same
  public `/system-status` response was therefore written to a mode-600
  temporary file, validated for allowlisted shape, scanned for forbidden field
  and value patterns, and compared with protected environment values without
  printing either the response or those values. Expanded DOM content was
  scanned separately.
- Per the Task 8 safety boundary, no OpenShift context, login, namespace, or
  resource query was attempted. The read-only preflight, probe requirements,
  immutable-digest rollback, and explicit approval gate are documented for a
  later approved deployment session.
- Review fix round 1 clarified that Agent local-history timestamps carry no
  freshness guarantee and expanded the feature filename scan from only `.env`
  to `.env`, `.env.local`, and every `.env.*` variant. The expanded scan passed.

## Final Review Checklist

- [x] Every design-spec section maps to a task above.
- [x] Backend full suite passes with zero real IBM calls from tests.
- [x] Frontend full suite, lint and production build pass.
- [x] `/healthz` remains shallow and exact.
- [x] `/readyz` depends only on PostgreSQL.
- [x] `/system-status` contains only allowlisted public fields.
- [x] Manual refresh does not invoke LLM, WXO runs or COS writes.
- [x] Three Agents use a live WXO registration check; timestamp-only local history scans at most the newest 500 events, has no freshness guarantee, and never changes a failed live check to `ready`.
- [x] OpenLLMetry failure does not change capability or overall status.
- [x] Desktop and mobile both expose `/status`.
- [x] User-flow notifications appear only for actionable limited/unavailable states.
- [x] Existing Loan form, PDF, presets, retry, application list and log viewer behavior remain intact.
- [x] No runtime database, logs or secrets are committed.
- [x] Public OpenShift deployment remains behind a separate explicit approval gate.

# Loan Demo Status 設計規格

日期：2026-09-04

狀態：已由使用者確認

範圍：`archived-apps/loan-preprocessing-agents` 的 React 前端與 FastAPI 後端

## 1. 目的

Loan POC 同時依賴 FastAPI、PostgreSQL、IBM Cloud Object Storage、watsonx.ai、watsonx Orchestrate Agents 與 OpenLLMetry。使用者目前只能在送件失敗或處理卡住後，才知道某個周邊服務可能有問題。

本功能要提供一個容易理解的 `Demo status` 頁面，先回答一般使用者最在意的問題：

- 現在能不能送件？
- 文件能不能分析？
- Agent 能不能完成貸款判斷？
- 既有申請能不能查看？
- 如果某項功能不可用，使用者現在應該怎麼做？

技術服務名稱與診斷資訊屬於第二層，預設收合，供 POC 展示人員或維運人員查閱。

## 2. 設計原則與依據

1. **以使用者功能呈現狀態，而不是先列基礎設施。** Atlassian Statuspage 建議以使用者依賴的 components 組織資訊，事故訊息要描述使用者受到的影響，而不是只顯示技術錯誤：<https://support.atlassian.com/statuspage/docs/show-service-status-with-components/>
2. **狀態不只靠顏色。** 每個狀態都要同時具備圖示、文字與簡短說明，避免色覺差異造成誤判。Carbon 也建議控制同時出現的狀態指標數量，避免資訊過載：<https://carbondesignsystem.com/patterns/status-indicator-pattern/>
3. **只在真正影響操作時顯示通知。** 受影響頁面使用 inline notification；不要因非關鍵的觀測服務故障，打斷一般使用者流程：<https://carbondesignsystem.com/components/notification/usage/>
4. **Kubernetes probes 與人看的狀態頁分離。** `/healthz`、`/readyz` 與周邊服務狀態用途不同，避免外部服務暫時延遲造成 Pod 被錯誤重啟：<https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/>
5. **健康檢查不能主動執行昂貴業務流程。** 狀態頁不可因重新整理就呼叫 LLM、建立 WXO thread 或執行三個 Agents。
6. **不假裝確定。** 若只能確認設定存在，畫面就顯示 `Configured`；若只有歷史執行證據，就顯示 `Last successful run`，不可包裝成即時健康。

## 3. 選定方案

採用「雙層狀態頁」：

- 第一層：四個一般使用者看得懂的功能狀態。
- 第二層：可展開的技術服務狀態與最近一次 Agent 執行資訊。

未採用方案：

- **純基礎設施 dashboard：** FastAPI、PostgreSQL、COS、WXO 全部平鋪，一般使用者難以判斷自己能做什麼。
- **單一綠燈／紅燈：** 過度簡化；部分功能故障時會讓使用者以為整個 Demo 都不能使用。
- **一般使用者與管理者各做一頁：** 對目前 POC 規模過重，也會增加導覽與維護成本。

## 4. 資訊架構

### 4.1 導覽入口

- Desktop header 增加 `Demo status`。
- Mobile side navigation 同步增加 `Demo status`，不可只出現在桌面版。
- 路由：`/status`。
- 導覽文字保持英文，與現有 `Apply`、`My Applications`、`Loan Calculator` 一致。

### 4.2 頁面結構

```text
Demo status                                      Refresh

[icon] Demo ready
       You can submit and review loan applications.
       Last checked 15 seconds ago

What you can do now

[Ready] Submit an application
        Online form and PDF upload are available.

[Ready] Process documents
        Uploaded documents can be extracted and validated.

[Ready] Generate a loan decision
        Agent processing is available. Results may take 2–4 minutes.

[Ready] View applications
        Application history and processing details are available.

[>] Technical details
```

頁面預設不顯示原始 endpoint、CRN、project ID、instance ID、agent ID、token、stack trace 或供應商回傳全文。

### 4.3 第一層：使用者功能

固定只顯示四項，避免指標過多：

| 功能 | 使用者問題 | 主要相依服務 |
|---|---|---|
| Submit an application | 表單與 PDF 是否能送出？ | Loan API、PostgreSQL、COS |
| Process documents | 上傳文件是否能抽取與驗證？ | COS、watsonx.ai、Document Processing Agent、Document Validation Agent |
| Generate a loan decision | 是否能完成最終貸款結果？ | WXO、Final Decision Agent，以及前序 Agent 結果 |
| View applications | 是否能查看申請與處理紀錄？ | Loan API、PostgreSQL |

### 4.4 第二層：Technical details

預設收合；展開後顯示：

- Loan API
- PostgreSQL
- IBM Cloud Object Storage
- watsonx.ai
- watsonx Orchestrate
  - Document Processing Agent
  - Document Validation Agent
  - Final Decision Agent
- OpenLLMetry（標註 `Does not affect demo availability`）

每列最多顯示：

- 服務顯示名稱
- 狀態文字與圖示
- 一句經過清理的摘要
- `Checked at` 或 `Last successful run`

不得顯示秘密資訊與完整錯誤內容。

## 5. 狀態模型

### 5.1 使用者功能狀態

| 狀態 | 意義 | 畫面語氣 |
|---|---|---|
| `ready` | 功能可正常使用 | Ready |
| `limited` | 可使用，但速度或結果可能受影響 | Limited |
| `unavailable` | 此功能目前無法完成 | Unavailable |
| `checking` | 正在取得最新狀態 | Checking |
| `unknown` | 無法完成狀態檢查，不等於功能一定故障 | Status unavailable |
| `not_configured` | POC 環境缺少此功能必要設定 | Not configured |

### 5.2 技術服務證據類型

技術細節除狀態外，必須保留證據語意：

- `Live check`：本次低成本連線檢查結果。
- `Configured`：必要設定完整，但未證明遠端服務現在可用。
- `Recent execution`：來自 `processing_runs`／`agent_events` 的最近真實業務執行。
- `Not verified`：目前沒有安全且低成本的確認方式。

### 5.3 整體狀態

只有四個使用者功能會影響頁首整體狀態；OpenLLMetry 不參與計算。

| 條件 | 整體狀態 | 建議文案 |
|---|---|---|
| 四項皆為 `ready` | `ready` | Demo ready — You can submit and review loan applications. |
| 至少一項仍可使用，但有 `limited`、`unavailable` 或 `not_configured` | `limited` | Some demo features are limited. Check the details below before continuing. |
| 送件與查看申請皆不可用 | `unavailable` | The demo is currently unavailable. Please try again later. |
| 狀態 API 本身無法回覆 | `unknown` | We could not check the demo status. You may still try the demo. |

`unknown` 不可自動顯示為紅色 outage；它表示「檢查失敗」，不是已證實服務中斷。

## 6. 後端邊界

### 6.1 `/healthz`

- 保留目前淺層行為，只確認 FastAPI process 能回應。
- 不查 PostgreSQL、COS、watsonx.ai、WXO 或 OpenLLMetry。
- 給 OpenShift liveness probe 使用。

### 6.2 `/readyz`

- 新增 readiness endpoint。
- 僅檢查應用程式接收流量不可缺少的 PostgreSQL，以輕量 `SELECT 1` 驗證。
- PostgreSQL 不可用時回非 2xx，讓 OpenShift 暫停導流，但不重啟 Pod。
- 不把 COS、watsonx.ai、WXO 或 OpenLLMetry 納入 readiness，避免外部服務問題引發部署層連鎖反應。

### 6.3 `/system-status`

- 新增提供前端狀態頁使用的唯讀 endpoint。
- 回傳經過清理的 capability 與 dependency 狀態。
- 因 POC 採自動登入且公開展示，此 endpoint 不依賴登入狀態，但資料格式必須視為公開資訊。
- 不接受 endpoint、credential 或 agent ID 等任意查詢參數，避免被利用成內網探測器。
- 不回傳原始 exception、response body、URL、CRN、ID 或環境變數值。

建議回應結構：

```json
{
  "overall": {
    "status": "limited",
    "title": "Some demo features are limited",
    "message": "You can view applications, but new document processing may be delayed."
  },
  "checked_at": "2026-09-04T10:20:30Z",
  "stale_after_seconds": 90,
  "capabilities": [
    {
      "id": "submit_application",
      "label": "Submit an application",
      "status": "ready",
      "message": "Online form and PDF upload are available."
    }
  ],
  "dependencies": [
    {
      "id": "postgresql",
      "label": "PostgreSQL",
      "status": "ready",
      "evidence": "live_check",
      "message": "Application storage is reachable.",
      "checked_at": "2026-09-04T10:20:29Z"
    }
  ]
}
```

## 7. 檢查策略

### 7.1 共通規則

- 所有遠端檢查都必須是唯讀、低成本、無業務副作用。
- 外部檢查彼此獨立並行；單一服務逾時不可拖垮整個狀態 endpoint。
- 每項外部檢查設定短 timeout，整體目標在 5 秒內回覆。
- 後端快取最近一次結果 30 秒；多位使用者同時開頁時不可同時轟炸 IBM Cloud 服務。
- 超過 90 秒仍無法更新時，前端標示 stale／status unavailable，不沿用綠燈假裝是即時狀態。
- 手動 Refresh 觸發重新檢查，但仍受單一執行與最短間隔保護。

### 7.2 各服務

| 服務 | 檢查方式 | 不做的事情 |
|---|---|---|
| Loan API | endpoint 能正常執行即代表 API 可回應 | 不呼叫自己的 `/healthz` 形成額外 HTTP loop |
| PostgreSQL | `SELECT 1` | 不建立表、不寫測試資料 |
| COS | 使用既有 credentials 做最低權限的 bucket metadata／可存取性檢查 | 不上傳、不刪除 object |
| watsonx.ai | 驗證必要設定；若官方有合適的低成本 metadata access API，再用它確認存取 | 不做模型 inference |
| WXO | 驗證必要設定；優先使用官方唯讀 metadata access；Agent 個別狀態搭配最近真實執行紀錄 | 不建立 thread、不執行 Agent |
| OpenLLMetry | 顯示 enabled／initialized 與設定狀態；若有可靠本地 export 證據再呈現 | 不把 collector 問題視為 Loan Demo outage |

若 watsonx.ai 或 WXO 沒有適合的官方低成本 endpoint，第一版應誠實顯示 `Configured`，並補充最近一次真實成功時間，不可用推測替代證據。

## 8. 最近執行結果

利用既有 PostgreSQL 資料：

- `processing_runs`：最近一次完整申請處理的開始、完成與結果。
- `agent_events`：三個 Agent 最近的 invoke／response／failure 證據。

需要建立唯讀查詢，依 Agent 類型整理：

- 最近一次成功時間
- 最近一次失敗時間
- 最近結果摘要（只允許固定、安全文案）

不可把文件內容、Applicant PII、模型完整輸出或 validation comments 放進狀態 API。

最近執行只是歷史證據，不等同即時 availability。UI 應明確寫成 `Last successful run`，不可寫成 `Healthy since`。

## 9. 前端互動

### 9.1 載入與重新整理

- 初次載入顯示頁面骨架，不顯示預設綠燈。
- Refresh 只讓按鈕與時間區域進入 inline loading，不遮住整頁。
- 重新整理期間保留上一筆資料，但標示 `Checking`。
- 成功後更新相對時間，例如 `Checked 15 seconds ago`。
- 瀏覽器頁面保持開啟時，每 30 秒更新相對時間；是否重新向後端取資料由快取策略控制。

### 9.2 錯誤與局部故障

- 狀態 API 完全失敗：保留頁面結構，整體顯示 `Status unavailable`，並提供 Retry。
- 單一 dependency 失敗：其他 capability 照常顯示，不把整頁替換成 error screen。
- 對使用者的文案說明「哪個操作受影響」與「可採取什麼動作」。
- 原始技術錯誤只寫入後端 log／trace，不進 UI。

### 9.3 受影響頁面的通知

只有當 capability 為 `limited` 或 `unavailable` 時，才在對應頁面放 Carbon inline notification：

- `Submit an application` 受影響：顯示於 Apply 頁送件區上方。
- `Process documents` 或 `Generate a loan decision` 受影響：顯示於 Apply 頁上方，但仍允許可安全執行的操作。
- `View applications` 受影響：顯示於 My Applications 頁列表上方。

第一版不在每頁常駐綠色通知，避免通知疲勞。

## 10. 視覺與無障礙

- 沿用現有 IBM Carbon 元件與 spacing，不建立另一套視覺語言。
- 以 `Tag`／狀態圖示／文字組合呈現，不只使用紅黃綠色。
- 文字對比符合 WCAG AA。
- 狀態更新區使用適當的 `aria-live="polite"`，避免每秒相對時間更新都被螢幕閱讀器播報。
- Technical details 使用可由鍵盤操作的 accordion。
- Mobile 單欄排列；狀態、標題、說明不可因窄螢幕被截斷。
- Refresh 維持至少 44 × 44 px 的可點擊範圍。
- Desktop 不使用超寬表格；Technical details 在窄螢幕改為垂直卡片資訊。

## 11. 安全與隱私

- `/system-status` 一律視為公開 endpoint。
- 不回傳任何 API key、bearer token、password、CRN、project ID、instance ID、agent ID、bucket 名稱或內部 endpoint。
- 錯誤採固定 allowlist 文案；不可直接把 `str(exception)` 回傳前端。
- 不回傳申請人、文件、SSN、passport、income 或模型內容。
- OpenLLMetry 保持既有 `TRACELOOP_TRACE_CONTENT=false` 隱私設定。
- Refresh 必須有 cache／cooldown，降低公開 endpoint 被用來放大外部 API 流量的風險。

## 12. 測試與驗收標準

### 12.1 後端

- `/healthz` 不因 PostgreSQL、COS、watsonx.ai、WXO 或 OpenLLMetry 模擬故障而失敗。
- `/readyz` 在 PostgreSQL 正常時回成功，PostgreSQL 無法連線時回非 2xx。
- `/system-status` 能處理每一個 dependency 的成功、逾時、未設定與例外。
- 單一 dependency 失敗時，其他 dependency 結果仍回傳。
- OpenLLMetry 故障不會將使用者 capability 或 overall 判為 unavailable。
- 回應 schema 不包含秘密值與原始 exception。
- 狀態計算規則有單元測試。
- Agent 最近執行查詢不回傳 PII 或模型原文。
- Cache、stale 與 refresh cooldown 有測試。

### 12.2 前端

- Desktop 與 mobile 導覽都能前往 `/status`。
- 初次載入、成功、limited、unavailable、unknown、stale 都有元件測試。
- Refresh 只顯示局部 loading，且避免重複點擊產生併發請求。
- Technical details 預設收合，可用鍵盤展開。
- 狀態圖示移除顏色後仍能靠文字辨認。
- 窄螢幕不遺失導覽、Refresh、四個 capability 或 Retry。
- Status API 失敗時，使用者仍可操作主導覽，不出現空白頁。

### 12.3 POC 驗收情境

1. 全部服務正常：顯示 `Demo ready`，四項 capability 都 Ready。
2. OpenLLMetry 關閉：Demo 仍 Ready，Technical details 顯示 tracing disabled／not configured。
3. WXO 不可用：查看歷史仍 Ready；文件處理與最終決策顯示 Limited 或 Unavailable，並提供可行下一步。
4. COS 不可用：送件與文件處理受影響；查看歷史仍可用。
5. PostgreSQL 不可用：送件與查看申請不可用；`/readyz` 失敗，但 `/healthz` 仍成功。
6. Status API 檢查逾時：前端顯示 `Status unavailable`，不誤報成所有服務 outage。
7. 最近沒有 Agent 執行紀錄：顯示 `No recent run`，不假裝已即時驗證 Agent。

## 13. 不在第一版範圍

- 不建立 Grafana／Prometheus 或完整維運監控平台。
- 不提供公開的 deep diagnostic 或「執行三個 Agents 測試」按鈕。
- 不建立 incident history、訂閱通知、SLA／uptime 百分比。
- 不修改 Loan 審核業務邏輯、Agent prompt 或 LLM 模型。
- 不把 DSCE UX、OpenShift cluster 其他專案或其他 namespace 納入此頁。
- 不取代 OpenShift probes、OpenLLMetry traces 或平台級告警。

## 14. 後續流程

1. 使用者確認本設計規格。
2. 依規格撰寫可執行的 implementation plan，列出檔案、測試與驗證命令。
3. 先以測試定義狀態計算與 API contract，再實作後端。
4. 實作 React／Carbon 狀態頁、導覽與受影響頁面的通知。
5. 先在本地 SIT 驗證，再依既有 OpenShift 部署與回滾程序更新 `itz-pl4yvb`。

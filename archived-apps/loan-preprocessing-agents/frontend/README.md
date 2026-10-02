# Financial LoanHub - Frontend

This is the frontend for the Financial LoanHub application, a modern web platform for applying for and managing loans. It is built with React, Vite, and the Carbon Design System.

## Features

-   **Automatic Demo Access:** The POC silently creates its demo JWT session without exposing login or registration screens.
-   **Persistent Demo Sessions:** Demo access remains available across page refreshes using `localStorage`.
-   **Protected APIs:** FastAPI endpoints remain protected by JWT even though authentication is invisible in the demo UI.
-   **Multi-Step Loan Application:** A user-friendly, multi-step form for submitting new loan applications with file uploads.
-   **PDF Application Upload:** An alternative application method allowing users to upload a pre-filled PDF.
-   **My Applications Dashboard:** A data table view for users to see the status and details of their submitted applications.
-   **Loan Calculator:** An interactive tool to help users estimate monthly loan payments.
-   **Demo Status:** A user-first view of four loan capabilities with collapsed, sanitized technical details.
-   **Responsive Design:** Styled with the Carbon Design System for a clean, professional, and responsive user interface.

## Tech Stack

-   **Framework:** [React](https://reactjs.org/)
-   **Build Tool:** [Vite](https://vitejs.dev/)
-   **UI Components:** [Carbon Design System](https://carbondesignsystem.com/)
-   **Routing:** [React Router](https://reactrouter.com/)
-   **State Management:** React Context API (for authentication and shared demo status)
-   **Language:** JavaScript (ES6+)

---

## Getting Started

### Prerequisites

-   [Node.js](https://nodejs.org/) (`^20.19.0 || >=22.12.0`)
-   [npm](https://www.npmjs.com/) or [yarn](https://yarnpkg.com/)
-   A running instance of the [backend server]

### Installation

1.  **Enter the frontend directory:**
    ```bash
    cd archived-apps/loan-preprocessing-agents/frontend
    ```

2.  **Install the locked dependencies:**
    ```bash
    npm ci
    ```

### Environment Configuration

During local development, no API environment variable is required. By default,
the client requests `/api`, and Vite proxies that prefix to
`http://127.0.0.1:8000` while removing `/api`. For example,
`/api/system-status` reaches the backend `/system-status` endpoint. This keeps
browser requests same-origin during development.

Set `VITE_API_URL` only when the frontend must call a different API origin,
such as a production deployment. Treat every `VITE_*` value as public because
Vite embeds it in browser assets; never place credentials, tokens, private
service endpoints, or IBM identifiers there. Do not commit local `.env` files.

### Running the Development Server

To start the local development server, run:

```bash
npm run dev
```

The application will be available at `http://localhost:5173` (or the next available port). The server will automatically reload when you make changes to the source code.

## Demo status page

Start the approved local runtime through the repository's `scripts/dev.sh` and
open `http://127.0.0.1:5316/status`. The public status page does not need a demo
login, so login/database failures cannot hide it. Application pages retain the
existing demo session requirement.

The page has four capability cards, **Check all**, and eight **Check now**
buttons inside Technical details. Each row shows the check time and received
safe diagnostics. The WXO and three Agent buttons check the same registration
group together. They do not execute an Agent or model. No status check verifies
model quota. OpenLLMetry is no longer shown.

The backend's 15-second group cooldown may return a previous result; the page
states when this happens. Results older than 90 seconds remain visible with an
outdated label, including errors. Agent execution history is separate from the
current registration check. API/network errors preserve prior evidence and
show a failed-check notice rather than declaring every provider unavailable.

The existing automatic metadata refresh remains every five minutes while the
status page is visible and online. It does not add LLM calls. Snapshot revisions
prevent out-of-order responses from replacing newer evidence. Apply/My
Applications notices use the freshness of each relevant capability.

### Isolated local status verification

From the repository root, prepare the Loan `.env` using `local.env.example` in
`archived-apps/loan-preprocessing-agents/`. Protect it with mode 0600. Use an
isolated database path and install the locked backend/frontend dependencies in
the task worktree. Then run:

```sh
scripts/dev.sh --check
scripts/dev.sh
```

Registered loopback ports are 8316 (API) and 5316 (UI). The launcher reads both
from `.env`, refuses occupied/default ports, and stops only its own processes.
`LOAN_STATUS_FIXTURES=true` starts the real status API/service with controlled
external transports: healthy database/COS/watsonx metadata and a WXO HTTP 401.
It has no loan processing or real cloud access. Set this flag to false only for
an explicitly configured real SIT environment. Do not use the older default-port
startup instructions for this verification workflow.

## Verify changes

Run the complete frontend checks before handoff:

```bash
npm test
npm run lint
npm run build
```

`npm test` runs the Vitest suite once, `npm run lint` checks the source with
ESLint, and `npm run build` creates the production bundle in `dist`.

## Building for Production

To create a production-ready build of the application, run:

```bash
npm run build
```

This will create an optimized `dist` folder with static assets that can be deployed to any web hosting service.

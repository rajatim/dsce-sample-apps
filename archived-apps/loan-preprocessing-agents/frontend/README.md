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

Open `http://127.0.0.1:5173/status`, or choose **Demo status** from either the
desktop header or the mobile side navigation. The page shows exactly four user
capabilities, a manual Refresh control, and Technical details that start
collapsed. If the status request fails, the page and primary navigation remain
usable and a Retry control replaces Refresh.

The browser consumes the backend's public, sanitized `/system-status`
response. Refresh requests `?refresh=true`, but backend cache and cooldown
rules still apply. Actionable `limited`, `not_configured`, or `unavailable`
states can show one warning on Apply or My Applications; normal `ready`,
initial loading, `unknown`, and stale-only states do not create a green success
banner or an outage notice.

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

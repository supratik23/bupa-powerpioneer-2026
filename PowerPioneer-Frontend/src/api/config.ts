/**
 * SINGLE POINT OF CONFIGURATION for the backend location.
 *
 * Every REST call in the app is made with a *partial* URL (e.g. "/shifts/"),
 * which is joined onto API_BASE_URL by the API client. WebSocket URLs are
 * joined onto WS_BASE_URL the same way (e.g. "/ws/notifications/").
 *
 * To point the frontend at another backend, either edit the defaults below
 * or set the variables in a `.env` / `.env.local` file (see `.env.example`):
 *
 *   VITE_API_BASE_URL=http://127.0.0.1:8000/api
 *   VITE_WS_BASE_URL=ws://127.0.0.1:8000        (optional, derived from the API URL)
 */

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api";

const trimSlash = (value: string) => value.replace(/\/+$/, "");

export const API_BASE_URL: string = trimSlash(
  import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL,
);

/** ws(s)://host[:port] derived from API_BASE_URL unless explicitly configured. */
function deriveWsBase(apiBase: string): string {
  const url = new URL(apiBase, window.location.origin);
  const protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${url.host}`;
}

export const WS_BASE_URL: string = trimSlash(
  import.meta.env.VITE_WS_BASE_URL || deriveWsBase(API_BASE_URL),
);

/** Join a partial REST path (e.g. "/shifts/") onto the configured API base URL. */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * ShiftGuard AI agent (PowerPioneer-AI/langgraph-agent, FastAPI on port 8001).
 * Serves the check-in question after an appointment is completed and scores the answer.
 * Override with VITE_AGENT_BASE_URL.
 */
export const AGENT_BASE_URL: string = trimSlash(
  import.meta.env.VITE_AGENT_BASE_URL || "http://127.0.0.1:8001",
);

/** How often the app asks the agent for a supportive nudge (ms). Override with VITE_NUDGE_INTERVAL_MS. */
export const NUDGE_INTERVAL_MS: number = Number(import.meta.env.VITE_NUDGE_INTERVAL_MS) || 60_000;

/** A nudge the user doesn't respond to hides itself after this long (ms). Override with VITE_NUDGE_VISIBLE_MS. */
export const NUDGE_VISIBLE_MS: number = Number(import.meta.env.VITE_NUDGE_VISIBLE_MS) || 10_000;

/** Join a partial WebSocket path (e.g. "/ws/notifications/") onto the WS base URL. */
export function wsUrl(path: string): string {
  return `${WS_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

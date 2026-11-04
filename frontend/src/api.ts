import type { AskResponse, Summary } from "./types";

const TIMEOUT_MS = 180_000;

/** A failure the UI can explain. `retryable` decides whether a Retry button is offered. */
export class ApiError extends Error {
  constructor(message: string, public retryable: boolean) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "TimeoutError";
    throw new ApiError(
      timedOut ? "The request timed out." : "Could not reach the backend, so no answer was produced. Is it running?",
      true,
    );
  }
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await response.json().catch(() => null);
  if (body?.error) return new ApiError(body.error.message, body.error.retryable);
  if (response.status === 422) return new ApiError("Please enter a question of up to 1,000 characters.", false);
  return new ApiError(`The server returned an error (HTTP ${response.status}).`, response.status >= 500);
}

export const getSummary = () => request<Summary>("/summary");

export const ask = (question: string) =>
  request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

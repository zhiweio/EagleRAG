/** API call error: carries HTTP status, message, and raw response body. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Extract a readable error message from a hey-api discriminated union or fetch exception. */
export function apiErrorFromUnknown(error: unknown, fallbackStatus = 0): ApiError {
  if (error instanceof ApiError) return error;
  if (typeof error === "object" && error !== null && "detail" in error) {
    return new ApiError(fallbackStatus, String((error as { detail: unknown }).detail), error);
  }
  if (error instanceof Error) {
    const match = /^SSE failed: (\d+)/.exec(error.message);
    const status = match ? Number(match[1]) : fallbackStatus;
    return new ApiError(status, error.message, error);
  }
  return new ApiError(fallbackStatus, String(error), error);
}

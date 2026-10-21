import { apiClient } from "@/lib/axios";

import { screenStateFromHttp, type ScreenState } from "./screens/status";

export type ApiError = { status: number; code: string; details: string };

/** Normalise an axios error into status + the backend's {error, details}. */
export function apiError(err: unknown): ApiError {
  const e = err as { response?: { status?: number; data?: { error?: string; details?: unknown; detail?: string } } };
  const status = e.response?.status ?? 0;
  const data = e.response?.data ?? {};
  const details =
    typeof data.details === "string"
      ? data.details
      : data.details
        ? JSON.stringify(data.details)
        : (data.detail ?? "");
  return { status, code: data.error ?? (status ? `http_${status}` : "network"), details };
}

export function stateFor(err: unknown): ScreenState {
  return screenStateFromHttp(apiError(err).status || 500);
}

/** A short sentence for a failed action, in the interface's voice. */
export function errorText(err: unknown): string {
  const { status, code, details } = apiError(err);
  if (status === 0) return "The server did not answer. Check that the API is running.";
  if (status === 403) return details || "You don't have permission to do this.";
  if (status === 404) return "Not found, or you can't see it.";
  if (status === 409 && code === "private_only") return "Your org only allows self-hosted AI, and none is set up.";
  if (status === 429) return details || "Too many requests. Try again in a minute.";
  if (status === 501) return details || "This feature is switched off for your organization.";
  return details || code;
}

const base = "/api/v2";

export const api = {
  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    return (await apiClient.get<T>(base + path, { params })).data;
  },
  async post<T>(path: string, body: unknown = {}): Promise<T> {
    return (await apiClient.post<T>(base + path, body)).data;
  },
  async put<T>(path: string, body: unknown = {}): Promise<T> {
    return (await apiClient.put<T>(base + path, body)).data;
  },
  async patch<T>(path: string, body: unknown = {}): Promise<T> {
    return (await apiClient.patch<T>(base + path, body)).data;
  },
  async del(path: string): Promise<void> {
    await apiClient.delete(base + path);
  },
};

/** Multipart upload (meeting recordings). The browser sets the boundary header itself. */
export async function apiClientUpload<T>(path: string, body: FormData): Promise<T> {
  return (await apiClient.post<T>(base + path, body, { headers: { "Content-Type": undefined }, timeout: 0 })).data;
}

/** Public, signed-out endpoints under /api/public (certificate verification, portfolios). */
export async function publicGet<T>(path: string): Promise<T> {
  return (await apiClient.get<T>(`/api/public${path}`)).data;
}

/** Lists come back as arrays or as {results: [...]}. */
export function rowsOf<T>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[];
  if (value && typeof value === "object" && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: T[] }).results;
  }
  return [];
}

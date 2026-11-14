import { getApiToken } from "../auth";
import type { CalendarResult, FeedResponse, Preferences, Profile, SyncResult } from "../types";

const apiBase = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getApiToken();
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let code = "request_failed";
    let message = "Something went wrong. Please try again.";
    try {
      const payload = await response.json();
      code = payload?.error?.code || code;
      message = payload?.error?.message || message;
    } catch {
      // Ignore unstructured response bodies to avoid displaying vendor details.
    }
    throw new ApiError(response.status, code, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getProfile = () => request<Profile>("/me");

export const updatePreferences = (preferences: Preferences) =>
  request<Profile>("/me/preferences", { method: "PUT", body: JSON.stringify(preferences) });

export function getOpportunities(filters: { q?: string; category?: string; priority?: string; saved?: boolean } = {}) {
  const params = new URLSearchParams();
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.category) params.set("category", filters.category);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.saved) params.set("saved", "true");
  params.set("limit", "50");
  return request<FeedResponse>(`/opportunities?${params.toString()}`);
}

export const syncInbox = () => request<SyncResult>("/sync", { method: "POST" });

export const setSaved = (id: string, saved: boolean) =>
  request<void>(`/opportunities/${encodeURIComponent(id)}/save`, { method: saved ? "POST" : "DELETE" });

export function createCalendarEvent(input: {
  opportunity_id: string;
  confirmed: true;
  all_day: boolean;
  start: string;
  end: string;
  time_zone: string;
}) {
  return request<CalendarResult>("/calendar/events", { method: "POST", body: JSON.stringify(input) });
}

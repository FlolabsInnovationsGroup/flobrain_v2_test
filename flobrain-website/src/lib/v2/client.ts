import { apiClient } from "@/lib/axios";
import type { components } from "@/lib/v2/schema";

export type V2Me = components["schemas"]["Me"];
export type V2TokenPair = components["schemas"]["TokenPair"];

const ACCESS_TOKEN_KEY = "flobrain_access_token";
const REFRESH_TOKEN_KEY = "flobrain_refresh_token";

export function storeV2Tokens(tokens: V2TokenPair) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access);
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh);
}

export function clearV2Tokens() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem("flobrain_outbox_v1"); // queued messages never outlive the session (review 10-13)
  void navigator.serviceWorker?.getRegistration?.().then((reg) => reg?.pushManager?.getSubscription()).then((sub) => sub?.unsubscribe()).catch(() => undefined);
}

export function v2Client() {
  return {
    async me() {
      const res = await apiClient.get<V2Me>("/api/v2/me");
      return res.data;
    },
    async signin(email: string, password: string) {
      const res = await apiClient.post<V2TokenPair>("/api/v2/auth/signin", {
        email,
        password,
      });
      storeV2Tokens(res.data);
      return res.data;
    },
    async firstLogin(password: string) {
      const res = await apiClient.post<V2TokenPair>("/api/v2/auth/first-login", {
        password,
      });
      storeV2Tokens(res.data);
      return res.data;
    },
    async forgotPassword(email: string) {
      await apiClient.post("/api/v2/auth/password/forgot", { email });
    },
    async resetPassword(token: string, password: string) {
      await apiClient.post("/api/v2/auth/password/reset", { token, password });
    },
    async orgs(slug?: string) {
      const res = await apiClient.get<Array<{ id: string; slug: string; name: string }>>("/api/v2/orgs", {
        params: slug ? { slug } : undefined,
      });
      return res.data;
    },
    async members(orgId: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/members`,
      );
      return res.data;
    },
    async member(orgId: string, userId: string) {
      const res = await apiClient.get<Record<string, unknown>>(`/api/v2/orgs/${orgId}/members/${userId}`);
      return res.data;
    },
    async tasks(orgId: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/tasks`,
      );
      return res.data;
    },
    async moveTask(orgId: string, taskId: string, status: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/tasks/${taskId}/move`, { status });
      return res.data;
    },
    async assignTask(orgId: string, taskId: string, userId: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/tasks/${taskId}/assign`, { user_id: userId });
      return res.data;
    },
    async timer(orgId: string) {
      const res = await apiClient.get<{ running: { id: string; description: string } | null }>(
        `/api/v2/orgs/${orgId}/timer`,
      );
      return res.data;
    },
    async startTimer(orgId: string, description = "") {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/timer/start`, { description });
      return res.data;
    },
    async stopTimer(orgId: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/timer/stop`, {});
      return res.data;
    },
    async dashboardMe(orgId: string) {
      const res = await apiClient.get<{ seconds_7d: number; impact_score: number | null }>(
        `/api/v2/orgs/${orgId}/dashboard/me`,
      );
      return res.data;
    },
    async reportMe(orgId: string, period?: string) {
      const res = await apiClient.get<{ seconds: number; entries: number; period: string }>(
        `/api/v2/orgs/${orgId}/time-reports/me`,
        { params: period ? { period } : undefined },
      );
      return res.data;
    },
    async timeEntries(orgId: string) {
      const res = await apiClient.get<{
        results: Array<{ seconds: number; started_at?: string; ended_at?: string | null }>;
      }>(`/api/v2/orgs/${orgId}/time-entries`);
      return res.data;
    },
    async calendar(orgId: string) {
      const res = await apiClient.get<Array<{ id: string; title: string; due_on: string; kind: string }>>(
        `/api/v2/orgs/${orgId}/calendar`,
      );
      return res.data;
    },
    async missionControl(orgId: string, team?: string) {
      const res = await apiClient.get<Record<string, unknown>>(`/api/v2/orgs/${orgId}/mission-control`, {
        params: team ? { team } : undefined,
      });
      return res.data;
    },
    async grants(orgId: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/grants`,
      );
      return res.data;
    },
    async permissionRequests(orgId: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/permission-requests`,
      );
      return res.data;
    },
    async decideRequest(orgId: string, requestId: string, decision: "approve" | "reject") {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/permission-requests/${requestId}/${decision}`, {});
      return res.data;
    },
    async revokeGrant(orgId: string, grantId: string) {
      await apiClient.delete(`/api/v2/orgs/${orgId}/grants/${grantId}`);
    },
    async rooms(orgId: string, q?: string) {
      const res = await apiClient.get<Array<Record<string, unknown>>>(`/api/v2/orgs/${orgId}/rooms`, {
        params: q ? { q } : undefined,
      });
      return res.data;
    },
    async room(orgId: string, roomId: string) {
      const res = await apiClient.get<Record<string, unknown>>(`/api/v2/orgs/${orgId}/rooms/${roomId}`);
      return res.data;
    },
    async roomMessages(orgId: string, roomId: string, translateTo?: string, cursor?: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>>; next?: string | null }>(
        `/api/v2/orgs/${orgId}/rooms/${roomId}/messages`,
        { params: { ...(translateTo ? { translate_to: translateTo } : {}), ...(cursor ? { cursor } : {}) } },
      );
      return res.data;
    },
    async postMessage(orgId: string, roomId: string, body: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/rooms/${roomId}/messages`, { body });
      return res.data;
    },
    async announcements(orgId: string) {
      const res = await apiClient.get<Array<Record<string, unknown>>>(`/api/v2/orgs/${orgId}/announcements`);
      return res.data;
    },
    async notifications(orgId: string, unread?: boolean) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/notifications`,
        { params: unread ? { unread: 1 } : undefined },
      );
      return res.data;
    },
    async readNotifications(orgId: string, ids?: string[]) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/notifications/read`, ids ? { ids } : {});
      return res.data;
    },
    async meetings(orgId: string, roomId: string) {
      const res = await apiClient.get<Array<Record<string, unknown>>>(
        `/api/v2/orgs/${orgId}/rooms/${roomId}/meetings`,
      );
      return res.data;
    },
    async createMeeting(orgId: string, roomId: string, title: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/rooms/${roomId}/meetings`, { title });
      return res.data;
    },
    async recordings(orgId: string, roomId: string, ordering?: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(
        `/api/v2/orgs/${orgId}/rooms/${roomId}/recordings`,
        { params: ordering ? { ordering } : undefined },
      );
      return res.data;
    },
    async meetingSummary(orgId: string, meetingId: string) {
      const res = await apiClient.get<Record<string, unknown>>(`/api/v2/orgs/${orgId}/meetings/${meetingId}/summary`);
      return res.data;
    },
    async confirmActionItem(orgId: string, meetingId: string, itemId: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/meetings/${meetingId}/action-items/${itemId}/to-task`, {
        confirm: true,
      });
      return res.data;
    },
    async roomDocs(orgId: string, roomId: string) {
      const res = await apiClient.get<Array<Record<string, unknown>>>(`/api/v2/orgs/${orgId}/rooms/${roomId}/docs`);
      return res.data;
    },
    async createDoc(orgId: string, roomId: string, title: string, contentText = "") {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/rooms/${roomId}/docs`, {
        title,
        content_text: contentText,
      });
      return res.data;
    },
    async patchDoc(orgId: string, docId: string, data: { version: number; title?: string; content_text?: string }) {
      const res = await apiClient.patch(`/api/v2/orgs/${orgId}/docs/${docId}`, data);
      return res.data;
    },
    async tools(orgId: string) {
      const res = await apiClient.get<Array<Record<string, unknown>>>(`/api/v2/orgs/${orgId}/tools`);
      return res.data;
    },
    async createTool(orgId: string, name: string, url: string) {
      const res = await apiClient.post(`/api/v2/orgs/${orgId}/tools`, { name, url });
      return res.data;
    },
    async deleteTool(orgId: string, toolId: string) {
      await apiClient.delete(`/api/v2/orgs/${orgId}/tools/${toolId}`);
    },
    async search(orgId: string, q: string, types?: string) {
      const res = await apiClient.get<{ results: Array<Record<string, unknown>> }>(`/api/v2/orgs/${orgId}/search`, {
        params: { q, ...(types ? { types } : {}) },
      });
      return res.data;
    },
  };
}

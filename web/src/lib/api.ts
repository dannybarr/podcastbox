import type { Episode, Job, Mail, Settings, SystemStatus } from "./types";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, cache: "no-store" });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* The body was not JSON. */
    }
    if (Array.isArray(detail)) {
      detail = detail.map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : String(item))).join(" ");
    }
    throw new Error(typeof detail === "string" ? detail : "The request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function today() {
  return api<{ episode: Episode | null }>("/api/episodes/today");
}

export function episode(id: string) {
  return api<Episode>(`/api/episodes/${id}`);
}

export function episodes() {
  return api<{ episodes: Episode[] }>("/api/episodes");
}

export function messages(includeNoise = true) {
  return api<{ messages: Mail[] }>(`/api/messages?include_noise=${includeNoise ? "true" : "false"}`);
}

export function message(id: string) {
  return api<Mail>(`/api/messages/${id}`);
}

export function settings() {
  return api<Settings>("/api/settings");
}

export function system() {
  return api<SystemStatus>("/api/system");
}

export async function waitForJob(jobId: string): Promise<Job> {
  for (let attempt = 0; attempt < 900; attempt += 1) {
    const job = await api<Job>(`/api/jobs/${jobId}`);
    if (job.status !== "running") return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("That job is still running. Leave this page open and check the archive in a minute.");
}

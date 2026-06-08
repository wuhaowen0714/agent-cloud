import type { AgentConfig, ContextDocument, FileEntry, Message, Session, Skill, User } from "../types"
import { authHeader, onUnauth, refreshAccess, setAccess } from "./auth"

async function http<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeader(), ...(init?.headers ?? {}) },
  })
  if (res.status === 401 && retry) {
    // access 过期 → 用 refresh cookie 静默换一枚,重试一次;再失败 → 登出。
    const tok = await refreshAccess()
    if (tok) return http<T>(path, init, false)
    onUnauth()
    throw new Error("unauthorized")
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

interface AuthResp {
  access_token: string
  user: User
}

async function _blobUrl(path: string, attachment = false): Promise<string> {
  // <img>/<a> 带不了 Authorization header,故下载/预览改 fetch(带 token)→ blob URL。
  const q = `path=${encodeURIComponent(path)}${attachment ? "&attachment=true" : ""}`
  const res = await fetch(`/api/files/raw?${q}`, { headers: authHeader() })
  if (!res.ok) throw new Error(`file fetch failed: ${res.status}`)
  return URL.createObjectURL(await res.blob())
}

export const api = {
  // ── auth ──
  register: async (email: string, password: string) => {
    const r = await http<AuthResp>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    })
    setAccess(r.access_token)
    return r.user
  },
  login: async (email: string, password: string) => {
    const r = await http<AuthResp>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    })
    setAccess(r.access_token)
    return r.user
  },
  logout: () => http<void>("/auth/logout", { method: "POST" }),
  me: () => http<User>("/auth/me"),

  // ── agents / sessions(user 由 token 推导)──
  listAgents: () => http<AgentConfig[]>("/agent-configs"),
  createAgent: (body: { name: string; model: string; provider: string }) =>
    http<AgentConfig>("/agent-configs", { method: "POST", body: JSON.stringify(body) }),
  listSessions: () => http<Session[]>("/sessions"),
  createSession: (body: { agent_config_id: string; title?: string }) =>
    http<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  listMessages: (sessionId: string) => http<Message[]>(`/sessions/${sessionId}/messages`),

  // ── files ──
  listFiles: (path: string) => http<FileEntry[]>(`/files?path=${encodeURIComponent(path)}`),
  previewUrl: (path: string) => _blobUrl(path, false),
  downloadUrl: (path: string) => _blobUrl(path, true),
  uploadFiles: async (path: string, files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append("files", f)
    const res = await fetch(`/api/files/upload?path=${encodeURIComponent(path)}`, {
      method: "POST",
      headers: authHeader(), // 不设 Content-Type,浏览器自动带 multipart boundary
      body: fd,
    })
    if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text().catch(() => "")}`)
    return (await res.json()) as FileEntry[]
  },
  mkdir: (path: string) =>
    http<FileEntry>("/files/mkdir", { method: "POST", body: JSON.stringify({ path }) }),
  moveFile: (src: string, dst: string) =>
    http<FileEntry>("/files/move", { method: "POST", body: JSON.stringify({ src, dst }) }),
  deleteFile: (path: string) =>
    http<void>(`/files?path=${encodeURIComponent(path)}`, { method: "DELETE" }),

  // ── agent config edit / docs / skills ──
  patchAgent: (
    id: string,
    body: Partial<
      Pick<AgentConfig, "name" | "model" | "provider" | "thinking_level" | "enabled_tools">
    >,
  ) => http<AgentConfig>(`/agent-configs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listDocs: (scope: string, agentId?: string) =>
    http<ContextDocument[]>(
      `/context-documents?scope=${scope}${agentId ? `&agent_id=${agentId}` : ""}`,
    ),
  putDoc: (scope: string, type: string, content: string, agentId?: string) =>
    http<ContextDocument>("/context-documents", {
      method: "PUT",
      body: JSON.stringify({ scope, type, content, ...(agentId ? { agent_id: agentId } : {}) }),
    }),
  listSkills: () => http<Skill[]>("/skills"),
  listRegistry: () => http<string[]>("/skills/registry"),
  installSkill: (name: string) =>
    http<Skill>("/skills/install", { method: "POST", body: JSON.stringify({ name }) }),
  deleteSkill: (id: string) => http<void>(`/skills/${id}`, { method: "DELETE" }),
  getAgentSkills: (agentId: string) => http<Skill[]>(`/agent-configs/${agentId}/skills`),
  setAgentSkills: (agentId: string, skillIds: string[]) =>
    http<Skill[]>(`/agent-configs/${agentId}/skills`, {
      method: "PUT",
      body: JSON.stringify({ skill_ids: skillIds }),
    }),
}

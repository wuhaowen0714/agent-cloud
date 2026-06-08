import type { AgentConfig, ContextDocument, FileEntry, Message, Session, Skill, User } from "../types"

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

export const api = {
  createUser: (email: string) => http<User>("/users", { method: "POST", body: JSON.stringify({ email }) }),
  getUser: (id: string) => http<User>(`/users/${id}`),
  listAgents: (userId: string) => http<AgentConfig[]>(`/agent-configs?user_id=${userId}`),
  createAgent: (body: { user_id: string; name: string; model: string; provider: string }) =>
    http<AgentConfig>("/agent-configs", { method: "POST", body: JSON.stringify(body) }),
  listSessions: (userId: string) => http<Session[]>(`/sessions?user_id=${userId}`),
  createSession: (body: { user_id: string; agent_config_id: string; title?: string }) =>
    http<Session>("/sessions", { method: "POST", body: JSON.stringify(body) }),
  listMessages: (sessionId: string) => http<Message[]>(`/sessions/${sessionId}/messages`),
  listFiles: (userId: string, path: string) =>
    http<FileEntry[]>(`/files?user_id=${userId}&path=${encodeURIComponent(path)}`),
  // 直接给 DOM 用的 URL(<img src> / 下载 <a href>);走 vite 代理的 /api 前缀
  fileRawUrl: (userId: string, path: string, attachment = false) =>
    `/api/files/raw?user_id=${userId}&path=${encodeURIComponent(path)}${attachment ? "&attachment=true" : ""}`,
  uploadFiles: async (userId: string, path: string, files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append("files", f)
    const res = await fetch(`/api/files/upload?user_id=${userId}&path=${encodeURIComponent(path)}`, {
      method: "POST",
      body: fd, // 不设 Content-Type,浏览器自动带 multipart boundary
    })
    if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text().catch(() => "")}`)
    return (await res.json()) as FileEntry[]
  },
  mkdir: (userId: string, path: string) =>
    http<FileEntry>("/files/mkdir", { method: "POST", body: JSON.stringify({ user_id: userId, path }) }),
  moveFile: (userId: string, src: string, dst: string) =>
    http<FileEntry>("/files/move", { method: "POST", body: JSON.stringify({ user_id: userId, src, dst }) }),
  deleteFile: (userId: string, path: string) =>
    http<void>(`/files?user_id=${userId}&path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  patchAgent: (
    id: string,
    body: Partial<Pick<AgentConfig, "name" | "model" | "provider" | "thinking_level" | "enabled_tools">>,
  ) => http<AgentConfig>(`/agent-configs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listDocs: (scope: string, ownerId: string) =>
    http<ContextDocument[]>(`/context-documents?scope=${scope}&owner_id=${ownerId}`),
  putDoc: (scope: string, type: string, ownerId: string, content: string) =>
    http<ContextDocument>("/context-documents", {
      method: "PUT",
      body: JSON.stringify({ scope, type, owner_id: ownerId, content }),
    }),
  listSkills: (userId: string) => http<Skill[]>(`/skills?user_id=${userId}`),
  listRegistry: () => http<string[]>("/skills/registry"),
  installSkill: (userId: string, name: string) =>
    http<Skill>("/skills/install", { method: "POST", body: JSON.stringify({ user_id: userId, name }) }),
  deleteSkill: (id: string) => http<void>(`/skills/${id}`, { method: "DELETE" }),
  getAgentSkills: (agentId: string) => http<Skill[]>(`/agent-configs/${agentId}/skills`),
  setAgentSkills: (agentId: string, skillIds: string[]) =>
    http<Skill[]>(`/agent-configs/${agentId}/skills`, {
      method: "PUT",
      body: JSON.stringify({ skill_ids: skillIds }),
    }),
}

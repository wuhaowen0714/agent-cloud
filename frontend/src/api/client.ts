import type {
  AgentConfig,
  ContextDocument,
  FileEntry,
  MemoryBlock,
  Message,
  ProviderCredential,
  Session,
  Skill,
  User,
  UserModel,
} from "../types"
import { authedFetch, setAccess } from "./auth"

// 带 HTTP 状态码的错误,便于上层(如 AuthGate)按 status 分支,而不是脆弱地 match 错误文案。
export class HttpError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = "HttpError"
    this.status = status
  }
}

async function http<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const res = await authedFetch(
    `/api${path}`,
    { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } },
    retry,
  )
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new HttpError(res.status, `${res.status} ${res.statusText}: ${body}`)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

interface AuthResp {
  access_token: string
  user: User
}

async function _blobUrl(path: string, attachment = false): Promise<string> {
  // <img>/<a> 带不了 Authorization header,故下载/预览改 authedFetch(带 token + 401 刷新)→ blob URL。
  const q = `path=${encodeURIComponent(path)}${attachment ? "&attachment=true" : ""}`
  const res = await authedFetch(`/api/files/raw?${q}`)
  if (!res.ok) throw new HttpError(res.status, `file fetch failed: ${res.status}`)
  return URL.createObjectURL(await res.blob())
}

export const api = {
  // ── auth ──(register/login 用 retry=false:401/409 是真实结果,不该触发 refresh)
  register: async (email: string, password: string) => {
    const r = await http<AuthResp>(
      "/auth/register",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    )
    setAccess(r.access_token)
    return r.user
  },
  login: async (email: string, password: string) => {
    const r = await http<AuthResp>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    )
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
  compactSession: (id: string) =>
    http<{ compacted: boolean }>(`/sessions/${id}/compact`, { method: "POST" }),

  // ── files ──
  listFiles: (path: string) => http<FileEntry[]>(`/files?path=${encodeURIComponent(path)}`),
  previewUrl: (path: string) => _blobUrl(path, false),
  downloadUrl: (path: string) => _blobUrl(path, true),
  uploadFiles: async (path: string, files: File[]) => {
    const fd = new FormData()
    for (const f of files) fd.append("files", f)
    // 不设 Content-Type,浏览器自动带 multipart boundary;authedFetch 负责 Bearer + 401 刷新。
    const res = await authedFetch(`/api/files/upload?path=${encodeURIComponent(path)}`, {
      method: "POST",
      body: fd,
    })
    if (!res.ok)
      throw new HttpError(res.status, `upload failed: ${res.status} ${await res.text().catch(() => "")}`)
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
      Pick<
        AgentConfig,
        "name" | "model" | "provider" | "thinking_level" | "enabled_tools" | "key_ref"
      >
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
  installSkillFromWorkspace: (path: string) =>
    http<Skill>("/skills/install-from-workspace", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  deleteSkill: (id: string) => http<void>(`/skills/${id}`, { method: "DELETE" }),
  getAgentSkills: (agentId: string) => http<Skill[]>(`/agent-configs/${agentId}/skills`),
  setAgentSkills: (agentId: string, skillIds: string[]) =>
    http<Skill[]>(`/agent-configs/${agentId}/skills`, {
      method: "PUT",
      body: JSON.stringify({ skill_ids: skillIds }),
    }),

  // ── provider credentials(BYO-Key)──
  listCredentials: () => http<ProviderCredential[]>("/credentials"),
  createCredential: (body: { name: string; base_url: string; api_key: string }) =>
    http<ProviderCredential>("/credentials", { method: "POST", body: JSON.stringify(body) }),
  deleteCredential: (id: string) => http<void>(`/credentials/${id}`, { method: "DELETE" }),

  // ── 智能体记忆(自整合单块)──
  getMemory: (scope: string, agentId?: string) =>
    http<MemoryBlock>(`/memory?scope=${scope}${agentId ? `&agent_id=${agentId}` : ""}`),
  putMemory: (scope: string, content: string, agentId?: string) =>
    http<MemoryBlock>("/memory", {
      method: "PUT",
      body: JSON.stringify({ scope, content, agent_id: agentId ?? null }),
    }),
  clearMemory: (scope: string, agentId?: string) =>
    http<MemoryBlock>(`/memory?scope=${scope}${agentId ? `&agent_id=${agentId}` : ""}`, {
      method: "DELETE",
    }),

  // ── 模型选单(预设之外的用户自定义模型)──
  listModels: () => http<UserModel[]>("/models"),
  addModel: (model: string) =>
    http<UserModel>("/models", { method: "POST", body: JSON.stringify({ model }) }),
  deleteModel: (id: string) => http<void>(`/models/${id}`, { method: "DELETE" }),
}

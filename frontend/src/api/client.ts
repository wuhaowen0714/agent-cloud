import type { AgentConfig, Message, Session, User } from "../types"

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
}

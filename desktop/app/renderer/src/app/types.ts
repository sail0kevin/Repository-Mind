/**
 * 桌面端页面共享的轻量领域类型。
 * 这些类型只描述前端交互状态，不替代后端 API 响应模型。
 */
export type WorkspaceTab = "catalog" | "qa" | "legacy" | "workflow" | "codegraph";
export type AgentStatus = "idle" | "thinking" | "done";
export type CodeGraphMode = "overview" | "search" | "calls" | "class";

export interface AgentConfig {
  id: string;
  name: string;
  role: string;
  status: AgentStatus;
  avatar: string;
  apiKey: string;
  baseUrl: string;
  model: string;
}

export interface DebateMessage {
  id: string;
  sender: string;
  role: string;
  content: string;
  isUser: boolean;
  timestamp: string;
}

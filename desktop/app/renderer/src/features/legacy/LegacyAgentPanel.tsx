import { Plus, Trash2, Users } from "lucide-react";

import type { AgentConfig } from "../../app/types";

export interface AgentRoleOption {
  value: string;
  label: string;
}

/**
 * Legacy 多角色配置面板。
 * 该功能继续兼容旧接口，但标题和说明明确它不是默认 Main Agent 问答流程。
 */
export function LegacyAgentPanel(props: {
  agents: AgentConfig[];
  editingAgentId: string | null;
  newAgentName: string;
  newAgentRole: string;
  roleOptions: AgentRoleOption[];
  onAddAgent: () => void;
  onEditingAgentChange: (id: string | null) => void;
  onNewAgentNameChange: (value: string) => void;
  onNewAgentRoleChange: (value: string) => void;
  onRemoveAgent: (id: string) => void;
  onUpdateAgent: (id: string, patch: Partial<AgentConfig>) => void;
}) {
  function roleLabel(role: string) {
    return props.roleOptions.find((item) => item.value === role)?.label ?? role;
  }

  return (
    <section className="af-section">
      <div className="af-section-title"><Users size={15} /> 高级功能 · Legacy 多角色</div>
      <p className="af-hint">普通问题请使用 Main Agent。这里保留固定多角色协作，便于兼容旧工作流。</p>
      <div className="af-agent-form">
        <input value={props.newAgentName} onChange={(event) => props.onNewAgentNameChange(event.target.value)} placeholder="Agent 名称" />
        <select value={props.newAgentRole} onChange={(event) => props.onNewAgentRoleChange(event.target.value)}>
          {props.roleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <button className="af-btn icon" onClick={props.onAddAgent} title="添加智能体"><Plus size={16} /></button>
      </div>
      <div className="af-agent-list">
        {props.agents.map((agent) => (
          <div key={agent.id} className={`af-agent-card ${agent.status}`}>
            <button className="af-agent-left" onClick={() => props.onEditingAgentChange(props.editingAgentId === agent.id ? null : agent.id)}>
              <span className="af-agent-avatar">{agent.avatar}</span>
              <span className="af-agent-info">
                <strong>{agent.name}</strong>
                <small>{roleLabel(agent.role)}</small>
              </span>
            </button>
            <span className={`af-agent-status ${agent.status}`}>{agent.status === "idle" ? "空闲" : agent.status === "thinking" ? "思考中" : "完成"}</span>
            <button className="af-icon-btn-small" onClick={() => props.onRemoveAgent(agent.id)} title="删除智能体"><Trash2 size={14} /></button>
            {props.editingAgentId === agent.id && (
              <div className="af-agent-config">
                <label className="af-field-inline"><span>名称</span><input value={agent.name} onChange={(event) => props.onUpdateAgent(agent.id, { name: event.target.value, avatar: event.target.value.slice(0, 1) || agent.avatar })} /></label>
                <label className="af-field-inline"><span>角色</span><select value={agent.role} onChange={(event) => props.onUpdateAgent(agent.id, { role: event.target.value })}>{props.roleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                <label className="af-field-inline"><span>专属 API Key（可选）</span><input type="password" value={agent.apiKey} onChange={(event) => props.onUpdateAgent(agent.id, { apiKey: event.target.value })} placeholder="留空使用全局设置" /></label>
                <label className="af-field-inline"><span>专属 Base URL（可选）</span><input value={agent.baseUrl} onChange={(event) => props.onUpdateAgent(agent.id, { baseUrl: event.target.value })} placeholder="https://api.longcat.chat/openai/v1" /></label>
                <label className="af-field-inline"><span>专属模型（可选）</span><input value={agent.model} onChange={(event) => props.onUpdateAgent(agent.id, { model: event.target.value })} placeholder="LongCat-2.0" /></label>
                <p className="af-hint">默认继承全局模型。跨平台接口时必须填写对应 Key；专属 Key 仅保留在本次请求内存中。</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { Command, Search, X } from "lucide-react";

import { Dialog } from "../components/ui/Dialog";
import { IconButton } from "../components/ui/IconButton";

export interface WorkbenchCommand {
  id: string;
  label: string;
  description: string;
  icon?: ReactNode;
  keywords?: string[];
  run: () => void;
}

/** 小白说明：命令面板只调用 App 已有操作，不会自己访问后端或增加虚假能力。 */
export function CommandBar(props: {
  isOpen: boolean;
  commands: WorkbenchCommand[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const listboxId = useId();
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return props.commands;
    return props.commands.filter((command) => [command.label, command.description, ...(command.keywords ?? [])].join(" ").toLocaleLowerCase().includes(needle));
  }, [props.commands, query]);

  useEffect(() => {
    if (props.isOpen) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [props.isOpen]);

  function run(command: WorkbenchCommand | undefined) {
    if (!command) return;
    props.onClose();
    command.run();
  }

  return (
    <Dialog isOpen={props.isOpen} onClose={props.onClose} title="RepoMind 命令面板" className="rm-command-dialog">
      <div className="rm-command-search">
        <Search size={17} aria-hidden="true" />
        <input
          autoFocus
          value={query}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          aria-controls={listboxId}
          aria-activedescendant={filtered[activeIndex] ? `${listboxId}-option-${filtered[activeIndex].id}` : undefined}
          aria-label="筛选 RepoMind 命令"
          placeholder="输入页面或操作，例如：问答、设置、工作流"
          onChange={(event) => { setQuery(event.target.value); setActiveIndex(0); }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") { event.preventDefault(); setActiveIndex((index) => Math.min(filtered.length - 1, index + 1)); }
            else if (event.key === "ArrowUp") { event.preventDefault(); setActiveIndex((index) => Math.max(0, index - 1)); }
            else if (event.key === "Enter") { event.preventDefault(); run(filtered[activeIndex]); }
          }}
        />
        <IconButton label="关闭命令面板" onClick={props.onClose}><X size={16} /></IconButton>
      </div>
      <div id={listboxId} className="rm-command-list" role="listbox" aria-label="可用命令">
        {filtered.map((command, index) => (
          <button
            key={command.id}
            id={`${listboxId}-option-${command.id}`}
            type="button"
            role="option"
            tabIndex={-1}
            aria-selected={index === activeIndex}
            className={`rm-command-item ${index === activeIndex ? "active" : ""}`}
            onMouseEnter={() => setActiveIndex(index)}
            onClick={() => run(command)}
          >
            <span className="rm-command-icon">{command.icon ?? <Command size={16} />}</span>
            <span><strong>{command.label}</strong><small>{command.description}</small></span>
          </button>
        ))}
        {filtered.length === 0 && <div className="rm-command-empty">没有匹配命令</div>}
      </div>
    </Dialog>
  );
}

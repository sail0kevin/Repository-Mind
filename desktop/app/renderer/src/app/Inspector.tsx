import { useState, type ReactNode } from "react";
import { Activity, Database, FileCode2 } from "lucide-react";

import { Tabs } from "../components/ui/Tabs";

type InspectorTab = "evidence" | "context" | "activity";

/** 右侧 Inspector 将证据、仓库上下文和运行信息分开，避免全部堆在一条长侧栏中。 */
export function Inspector(props: {
  evidence: ReactNode;
  context: ReactNode;
  activity: ReactNode;
  evidenceCount: number;
  onTabChange?: (tab: InspectorTab) => void;
}) {
  const [tab, setTab] = useState<InspectorTab>("evidence");

  function selectTab(nextTab: InspectorTab) {
    setTab(nextTab);
    props.onTabChange?.(nextTab);
  }

  return (
    <div className="rm-inspector">
      <Tabs
        idBase="inspector"
        ariaLabel="调查 Inspector"
        value={tab}
        onChange={selectTab}
        items={[
          { value: "evidence", label: <><FileCode2 size={13} /> Evidence</>, badge: props.evidenceCount ? String(props.evidenceCount) : undefined },
          { value: "context", label: <><Database size={13} /> 上下文</> },
          { value: "activity", label: <><Activity size={13} /> 活动</> },
        ]}
      />
      <div
        id={`inspector-panel-${tab}`}
        className="rm-inspector-content"
        role="tabpanel"
        aria-labelledby={`inspector-tab-${tab}`}
      >
        {tab === "evidence" && props.evidence}
        {tab === "context" && props.context}
        {tab === "activity" && props.activity}
      </div>
    </div>
  );
}

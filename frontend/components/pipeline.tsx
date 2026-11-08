import { Check, Circle, CircleAlert } from "lucide-react";
import { stages, type AirlockEvent } from "@/lib/models";
import { pipelineState } from "@/lib/presentation";

export function PipelineStages({ events }: { events: AirlockEvent[] }) {
  const state = pipelineState(events);
  return (
    <ol className="pipeline" aria-label="Analysis pipeline">
      {stages.map((stage, index) => (
        <li
          key={stage}
          className={`pipeline-${state[stage]}`}
          aria-current={state[stage] === "active" ? "step" : undefined}
        >
          <span className="stage-marker">
            {state[stage] === "done" ? (
              <Check size={14} />
            ) : state[stage] === "error" ? (
              <CircleAlert size={14} />
            ) : state[stage] === "active" ? (
              <Circle size={11} fill="currentColor" />
            ) : (
              index + 1
            )}
          </span>
          <span>
            {stage}
            <span className="sr-only">: {state[stage]}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

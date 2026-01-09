import { ActionsRow, Card } from "./common.jsx";

export function CollectorStep({ className, input, status, output }) {
  const layoutClass = className ? `step-layout ${className}` : "step-layout";
  const inputClass = input?.className ? `step-input ${input.className}` : "step-input";
  const statusClass = status?.className ? `step-status ${status.className}` : "step-status";
  const outputClass = output?.className ? `step-output ${output.className}` : "step-output";
  return (
    <div class={layoutClass}>
      {input ? (
        <Card title={input.title} className={inputClass}>
          {input.body}
          {input.actions ? <ActionsRow actions={input.actions} /> : null}
          {input.secondaryActions ? <ActionsRow actions={input.secondaryActions} className="actions-secondary" /> : null}
        </Card>
      ) : null}
      {status ? (
        <Card title={status.title} className={statusClass}>
          {status.body}
        </Card>
      ) : null}
      {output ? (
        <Card title={output.title} className={outputClass}>
          {output.body}
          {output.actions ? <ActionsRow actions={output.actions} /> : null}
          {output.secondaryActions ? <ActionsRow actions={output.secondaryActions} className="actions-secondary" /> : null}
        </Card>
      ) : null}
    </div>
  );
}

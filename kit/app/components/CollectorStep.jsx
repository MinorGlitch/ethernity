import { ActionsRow, Card } from "./common.jsx";

export function CollectorStep({ className, input, status, output }) {
  const layoutClass = className ? `step-layout ${className}` : "step-layout";
  return (
    <div class={layoutClass}>
      {input ? (
        <Card title={input.title} className="step-input">
          {input.body}
          {input.actions ? <ActionsRow actions={input.actions} /> : null}
        </Card>
      ) : null}
      {status ? (
        <Card title={status.title} className="step-status">
          {status.body}
        </Card>
      ) : null}
      {output ? (
        <Card title={output.title} className="step-output">
          {output.body}
          {output.actions ? <ActionsRow actions={output.actions} /> : null}
        </Card>
      ) : null}
    </div>
  );
}

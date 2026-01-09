import { formatBytes } from "../state/selectors.js";

export function Card({ title, children, className }) {
  const classes = className ? `card ${className}` : "card";
  return (
    <section class={classes}>
      {title ? <h3>{title}</h3> : null}
      {children}
    </section>
  );
}

export function ActionsRow({ actions }) {
  if (!actions || !actions.length) return null;
  return (
    <div class="row">
      {actions.map((action) => (
        <button
          class={action.className}
          disabled={action.disabled}
          onClick={action.onClick}
          type="button"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}

export function Field({
  id,
  label,
  value,
  placeholder,
  onInput,
  readOnly,
  type = "text",
  as = "input",
  className,
}) {
  const Tag = as === "textarea" ? "textarea" : "input";
  const tagProps = {
    id,
    value: value ?? "",
    placeholder,
    readOnly,
    onInput,
    class: className,
  };
  if (Tag === "input") {
    tagProps.type = type;
  }
  return (
    <>
      <label class="label" htmlFor={id}>{label}</label>
      <Tag {...tagProps} />
    </>
  );
}

export function StatusBlock({ status }) {
  const lines = status?.lines?.length ? status.lines.join("\n") : "";
  const className = status?.type ? `status ${status.type}` : "status";
  return <div class={className}>{lines}</div>;
}

export function DiagnosticsList({ items }) {
  return (
    <div class="diag-list">
      {items.map((item) => (
        <div class="diag-row">
          <div class="diag-label">{item.label}</div>
          <div class="diag-value">{item.value ?? "-"}</div>
        </div>
      ))}
    </div>
  );
}

export function SourceSummary({ label, detail }) {
  return (
    <div class="source-summary">
      <span class="source-label">{label}</span>
      <span class="source-detail">{detail}</span>
    </div>
  );
}

export function OutputTable({ files, onDownloadFile }) {
  if (!files.length) {
    return (
      <tbody>
        <tr class="empty-row">
          <td colSpan="3">No files extracted yet.</td>
        </tr>
      </tbody>
    );
  }
  return (
    <tbody>
      {files.map((file, index) => (
        <tr>
          <td>{file.path}</td>
          <td>{formatBytes(file.data.length)}</td>
          <td>
            <button class="secondary" onClick={() => onDownloadFile(index)}>
              Download
            </button>
          </td>
        </tr>
      ))}
    </tbody>
  );
}

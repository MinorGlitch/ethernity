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
  if (!status?.lines?.length) return null;
  const className = status?.type ? `status ${status.type}` : "status";
  return <div class={className}>{status.lines.join("\n")}</div>;
}

export function DiagnosticsList({ items }) {
  return (
    <div class="diag-list">
      {items.map((item, index) => {
        const rowClass = item.tone ? `diag-row ${item.tone}` : "diag-row";
        const valueClass = item.code ? "diag-value code" : "diag-value";
        return (
          <div key={`${item.label}-${index}`} class={rowClass}>
            <div class="diag-label">{item.label}</div>
            <div class={valueClass}>
              <div class="diag-main">{item.value ?? "-"}</div>
              {item.detail ? <div class="diag-detail">{item.detail}</div> : null}
            </div>
          </div>
        );
      })}
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

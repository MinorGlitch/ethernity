import { ActionsRow, Card, OutputTable, StatusBlock } from "./common.jsx";

export function RecoveredFiles({
  extractStatus,
  outputSubtitle,
  files,
  onClearOutput,
  onDownloadZip,
  onDownloadFile,
  hasOutput,
}) {
  const actions = [
    { label: "Clear output", className: "ghost", onClick: onClearOutput, disabled: !hasOutput },
    { label: "Download ZIP", className: "secondary", onClick: onDownloadZip, disabled: !hasOutput },
  ];
  return (
    <Card>
      <div class="row">
        <h3>Recovered files</h3>
        <div class="sub">{outputSubtitle}</div>
      </div>
      <ActionsRow actions={actions} />
      <StatusBlock status={extractStatus} />
      <table>
        <thead>
          <tr>
            <th>Path</th>
            <th>Size</th>
            <th>Download</th>
          </tr>
        </thead>
        <OutputTable files={files} onDownloadFile={onDownloadFile} />
      </table>
    </Card>
  );
}

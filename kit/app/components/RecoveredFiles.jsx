import { ActionsRow, Card, OutputTable, StatusBlock } from "./common.jsx";

function SuccessBanner({ fileCount }) {
  return (
    <div class="success-banner">
      <h3>
        <span class="success-icon">✓</span>
        Recovery Complete
      </h3>
      <p>
        Successfully recovered {fileCount} file{fileCount !== 1 ? "s" : ""}.
        Download individual files below or get everything as a ZIP.
      </p>
    </div>
  );
}

export function RecoveredFiles({
  extractStatus,
  outputSubtitle,
  files,
  onClearOutput,
  onDownloadZip,
  onDownloadFile,
  hasOutput,
  recoveryComplete,
}) {
  const actions = [
    { label: "Clear output", className: "ghost", onClick: onClearOutput, disabled: !hasOutput },
    { label: "Download all as ZIP", className: "secondary", onClick: onDownloadZip, disabled: !hasOutput },
  ];
  return (
    <Card>
      {recoveryComplete && hasOutput && <SuccessBanner fileCount={files.length} />}
      <div class="row row-between">
        <div>
          <h3>Recovered files</h3>
          <div class="sub">{outputSubtitle}</div>
        </div>
        <ActionsRow actions={actions} />
      </div>
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

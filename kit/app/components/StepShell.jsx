export function StepShell({ step, stepIndex, total, children }) {
  const title = step?.title ?? "Recovery step";
  const summary = step?.summary;
  return (
    <section class="panel step-shell">
      <div class="step-head">
        <div class="label">Step {stepIndex + 1} of {total}</div>
        <h2 class="step-heading">{title}</h2>
        {summary ? <p class="step-summary">{summary}</p> : null}
      </div>
      <div class="step-content">
        {children}
      </div>
    </section>
  );
}

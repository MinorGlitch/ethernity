export function StepShell({ step, stepIndex, total, children }) {
  const title = step?.title ?? "Recovery step";
  return (
    <section class="panel step-shell">
      <div class="step-head">
        <div class="label">Step {stepIndex + 1} of {total}</div>
        <h2 class="step-heading">{title}</h2>
      </div>
      <div class="step-content">
        {children}
      </div>
    </section>
  );
}

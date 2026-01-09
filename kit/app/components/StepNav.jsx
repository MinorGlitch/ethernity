export function StepNav({ steps, stepIndex, stepStates, onPrev, onNext, onJump }) {
  const total = steps.length;
  const canPrev = stepIndex > 0;
  const canNext = stepIndex < total - 1;
  const states = stepStates ?? [];

  return (
    <nav class="step-nav" aria-label="Recovery steps">
      <div class="step-nav-header">
        <div class="label">Recovery steps</div>
        <div class="step-progress">Step {stepIndex + 1} of {total}</div>
      </div>
      <div class="step-list">
        {steps.map((step, index) => {
          const active = index === stepIndex;
          const state = states[index] ?? { label: "Pending", tone: "idle" };
          const className = active ? "step-item active" : "step-item";
          const stateClass = `step-state ${state.tone || "idle"}`;
          return (
            <button
              key={step.id ?? index}
              class={className}
              type="button"
              aria-current={active ? "step" : undefined}
              onClick={() => onJump(index)}
            >
              <span class="step-index">{index + 1}</span>
              <span class="step-meta">
                <span class="step-name">{step.title}</span>
                <span class={stateClass}>{state.label}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div class="step-nav-actions">
        <button class="ghost" disabled={!canPrev} onClick={onPrev} type="button">
          Previous
        </button>
        <button disabled={!canNext} onClick={onNext} type="button">
          Next
        </button>
      </div>
    </nav>
  );
}

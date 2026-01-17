/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

export function StepNav({ steps, stepIndex, stepStates, onPrev, onNext, onJump }) {
  const total = steps.length;
  const canPrev = stepIndex > 0;
  const canNext = stepIndex < total - 1;
  const states = stepStates ?? [];

  return (
    <nav class="step-nav" aria-label="Recovery steps">
      <div class="step-nav-header">
        <div class="label">Recovery steps</div>
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

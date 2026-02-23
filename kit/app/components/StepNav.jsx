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

export function StepNav({ steps, stepIndex, onPrev, onNext, onJump }) {
  const total = steps.length;
  const canPrev = stepIndex > 0;
  const canNext = stepIndex < total - 1;
  const current = steps[stepIndex] ?? steps[0];

  return (
    <nav class="step-nav" aria-label="Recovery steps">
      <div class="step-nav-top">
        <div class="label">Step {stepIndex + 1} / {total}</div>
        <div class="step-nav-title">{current?.title ?? "Recovery step"}</div>
      </div>
      <label class="label" htmlFor="step-jump">Go to step</label>
      <select
        id="step-jump"
        value={String(stepIndex)}
        onChange={(event) => onJump(Number(event.currentTarget.value))}
      >
        {steps.map((step, index) => (
          <option key={step.id ?? index} value={String(index)}>
            {index + 1}. {step.title}
          </option>
        ))}
      </select>
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

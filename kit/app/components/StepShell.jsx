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

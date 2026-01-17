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

import { ActionsRow, Card } from "./common.jsx";

export function CollectorStep({ className, input, status, output }) {
  const layoutClass = className ? `step-layout ${className}` : "step-layout";
  const inputClass = input?.className ? `step-input ${input.className}` : "step-input";
  const statusClass = status?.className ? `step-status ${status.className}` : "step-status";
  const outputClass = output?.className ? `step-output ${output.className}` : "step-output";
  return (
    <div class={layoutClass}>
      {input ? (
        <Card title={input.title} className={inputClass}>
          {input.body}
          {input.actions ? <ActionsRow actions={input.actions} /> : null}
          {input.secondaryActions ? <ActionsRow actions={input.secondaryActions} className="actions-secondary" /> : null}
        </Card>
      ) : null}
      {status ? (
        <Card title={status.title} className={statusClass}>
          {status.body}
        </Card>
      ) : null}
      {output ? (
        <Card title={output.title} className={outputClass}>
          {output.body}
          {output.actions ? <ActionsRow actions={output.actions} /> : null}
          {output.secondaryActions ? <ActionsRow actions={output.secondaryActions} className="actions-secondary" /> : null}
        </Card>
      ) : null}
    </div>
  );
}

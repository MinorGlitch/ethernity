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

export function StatusStrip({ items }) {
  if (!items || !items.length) return null;
  return (
    <section class="panel status-strip">
      {items.map((item, index) => {
        const className = item.tone ? `status-item ${item.tone}` : "status-item";
        return (
          <div key={item.label ?? index} class={className}>
            <div class="status-label">{item.label}</div>
            <div class="status-value">{item.value}</div>
            {item.subLabel ? <div class="status-sub">{item.subLabel}</div> : null}
          </div>
        );
      })}
    </section>
  );
}

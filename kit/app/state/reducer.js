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

import { cloneState, createInitialState } from "./initial.js";

export function initialState() {
  return createInitialState();
}

export function reducer(state, action) {
  if (!state) {
    return createInitialState();
  }
  switch (action.type) {
    case "PATCH_STATE": {
      if (!action.patch || action.baseRevision !== state.revision) {
        return state;
      }
      return { ...state, ...action.patch, revision: state.revision + 1 };
    }
    case "MUTATE_STATE": {
      if (typeof action.mutate !== "function" || action.baseRevision !== state.revision) {
        return state;
      }
      const next = cloneState(state);
      action.mutate(next);
      next.revision = state.revision + 1;
      return next;
    }
    case "RESET": {
      const next = createInitialState();
      next.revision = state.revision + 1;
      return next;
    }
    default:
      return state;
  }
}

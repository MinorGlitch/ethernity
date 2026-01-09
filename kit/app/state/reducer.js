import { createInitialState } from "./initial.js";

export function initialState() {
  return createInitialState();
}

export function reducer(state, action) {
  if (!state) {
    return createInitialState();
  }
  switch (action.type) {
    case "REPLACE":
      return action.state;
    case "RESET":
      return createInitialState();
    default:
      return state;
  }
}

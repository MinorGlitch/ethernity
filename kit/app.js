import { createState, resetState } from "./app/state.js";
import { bindUI, updateUI } from "./app/ui.js";
import { createHandlers } from "./app/handlers.js";

const state = createState();
const ui = bindUI();

function render() {
  updateUI(state, ui);
}

const handlers = createHandlers({
  state,
  ui,
  updateUI: render,
});

resetState(state);
handlers.bind();
render();

const Fragment = Symbol("microact.fragment");

let rootState = null;
let renderScheduled = false;
let isRendering = false;
let currentInstance = null;
let pendingEffects = [];
const componentInstances = new Map();

export { Fragment };

export function jsx(type, props, key) {
  const normalized = props ? { ...props } : {};
  if (key !== undefined) {
    normalized.key = key;
  }
  return { type, props: normalized };
}

export const jsxs = jsx;
export const jsxDEV = jsx;

export function render(vnode, root) {
  rootState = { root, vnode };
  scheduleRender();
}

export function useState(initialValue) {
  const instance = requireCurrentInstance("useState");
  const slot = useHookSlot(instance, "state", () => {
    const value = typeof initialValue === "function" ? initialValue() : initialValue;
    return { value };
  });
  if (!slot.setValue) {
    slot.setValue = (nextValue) => {
      const next = typeof nextValue === "function" ? nextValue(slot.value) : nextValue;
      if (Object.is(next, slot.value)) {
        return;
      }
      slot.value = next;
      scheduleRender();
    };
  }
  return [slot.value, slot.setValue];
}

export function useReducer(reducer, initialArg, init) {
  const instance = requireCurrentInstance("useReducer");
  const slot = useHookSlot(instance, "reducer", () => ({
    value: init ? init(initialArg) : initialArg,
  }));
  if (!slot.dispatch) {
    slot.dispatch = (action) => {
      const next = reducer(slot.value, action);
      if (Object.is(next, slot.value)) {
        return;
      }
      slot.value = next;
      scheduleRender();
    };
  }
  return [slot.value, slot.dispatch];
}

export function useRef(initialValue) {
  const instance = requireCurrentInstance("useRef");
  const slot = useHookSlot(instance, "ref", () => ({
    ref: { current: initialValue },
  }));
  return slot.ref;
}

export function useEffect(effect, deps) {
  const instance = requireCurrentInstance("useEffect");
  const slot = useHookSlot(instance, "effect", () => ({
    deps: undefined,
    cleanup: null,
  }));
  if (depsChanged(slot.deps, deps)) {
    pendingEffects.push({ slot, effect, deps });
  }
}

function requireCurrentInstance(name) {
  if (!currentInstance) {
    throw new Error(`${name} must be called while rendering a component`);
  }
  return currentInstance;
}

function useHookSlot(instance, kind, init) {
  const index = instance.hookIndex++;
  const existing = instance.hooks[index];
  if (existing && existing.kind === kind) {
    return existing;
  }
  const slot = { kind, ...init() };
  instance.hooks[index] = slot;
  return slot;
}

function scheduleRender() {
  if (!rootState || renderScheduled) {
    return;
  }
  renderScheduled = true;
  queueMicrotask(flushRenderQueue);
}

function flushRenderQueue() {
  if (!rootState || isRendering) {
    return;
  }
  isRendering = true;
  try {
    while (renderScheduled && rootState) {
      renderScheduled = false;
      const seenPaths = new Set();
      pendingEffects = [];
      const focusSnapshot = captureFocusSnapshot(rootState.root);
      const fragment = document.createDocumentFragment();
      appendChildNode(fragment, rootState.vnode, "0", seenPaths);
      rootState.root.replaceChildren(fragment);
      pruneComponentInstances(seenPaths);
      restoreFocusSnapshot(rootState.root, focusSnapshot);
      flushEffects();
    }
  } finally {
    isRendering = false;
  }
}

function flushEffects() {
  const queue = pendingEffects;
  pendingEffects = [];
  for (const item of queue) {
    if (typeof item.slot.cleanup === "function") {
      try {
        item.slot.cleanup();
      } catch {
        // Ignore effect cleanup failures in the offline kit UI runtime.
      }
    }
    const cleanup = item.effect();
    item.slot.cleanup = typeof cleanup === "function" ? cleanup : null;
    item.slot.deps = item.deps;
  }
}

function pruneComponentInstances(seenPaths) {
  for (const [path, instance] of componentInstances.entries()) {
    if (seenPaths.has(path)) {
      continue;
    }
    for (const hook of instance.hooks) {
      if (hook?.kind === "effect" && typeof hook.cleanup === "function") {
        try {
          hook.cleanup();
        } catch {
          // Ignore cleanup failures during unmount.
        }
      }
    }
    componentInstances.delete(path);
  }
}

function appendChildNode(parent, vnode, path, seenPaths) {
  if (vnode === null || vnode === undefined || vnode === false || vnode === true) {
    return;
  }
  if (Array.isArray(vnode)) {
    for (let index = 0; index < vnode.length; index += 1) {
      appendChildNode(parent, vnode[index], `${path}.${index}`, seenPaths);
    }
    return;
  }
  if (typeof vnode === "string" || typeof vnode === "number") {
    parent.appendChild(document.createTextNode(String(vnode)));
    return;
  }
  if (typeof vnode.type === "function") {
    const instance = getComponentInstance(path, vnode.type);
    seenPaths.add(path);
    const previousInstance = currentInstance;
    currentInstance = instance;
    instance.hookIndex = 0;
    let rendered;
    try {
      rendered = vnode.type(vnode.props ?? {});
    } finally {
      currentInstance = previousInstance;
    }
    appendChildNode(parent, rendered, `${path}.0`, seenPaths);
    return;
  }
  if (vnode.type === Fragment) {
    appendChildren(parent, vnode.props?.children, `${path}.f`, seenPaths);
    return;
  }

  const element = document.createElement(vnode.type);
  applyProps(element, vnode.props ?? {});
  appendChildren(element, vnode.props?.children, `${path}.c`, seenPaths);
  parent.appendChild(element);
}

function appendChildren(parent, children, path, seenPaths) {
  if (children === null || children === undefined) {
    return;
  }
  if (Array.isArray(children)) {
    for (let index = 0; index < children.length; index += 1) {
      appendChildNode(parent, children[index], `${path}.${index}`, seenPaths);
    }
    return;
  }
  appendChildNode(parent, children, `${path}.0`, seenPaths);
}

function getComponentInstance(path, type) {
  const existing = componentInstances.get(path);
  if (existing && existing.type === type) {
    return existing;
  }
  const instance = { type, hooks: [], hookIndex: 0 };
  componentInstances.set(path, instance);
  return instance;
}

function applyProps(element, props) {
  for (const [name, value] of Object.entries(props)) {
    if (name === "children" || name === "key") {
      continue;
    }
    if (name === "ref") {
      assignRef(value, element);
      continue;
    }
    if (name.startsWith("on") && typeof value === "function") {
      const eventName = name.slice(2).toLowerCase();
      element.addEventListener(eventName, value);
      continue;
    }
    if (name === "class" || name === "className") {
      element.className = value ?? "";
      continue;
    }
    if (name === "htmlFor") {
      element.htmlFor = value ?? "";
      continue;
    }
    if (value === null || value === undefined || value === false) {
      continue;
    }
    if (value === true) {
      element.setAttribute(name, "");
      if (name in element) {
        element[name] = true;
      }
      continue;
    }
    if (name === "style" && value && typeof value === "object") {
      Object.assign(element.style, value);
      continue;
    }
    if (name in element) {
      try {
        element[name] = value;
        continue;
      } catch {
        // Fall back to attribute set below.
      }
    }
    element.setAttribute(name, String(value));
  }
}

function assignRef(ref, value) {
  if (!ref) {
    return;
  }
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  if (typeof ref === "object") {
    ref.current = value;
  }
}

function depsChanged(prev, next) {
  if (next === undefined) {
    return true;
  }
  if (!prev) {
    return true;
  }
  if (prev.length !== next.length) {
    return true;
  }
  for (let index = 0; index < next.length; index += 1) {
    if (!Object.is(prev[index], next[index])) {
      return true;
    }
  }
  return false;
}

function captureFocusSnapshot(root) {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !root.contains(active) || !active.id) {
    return null;
  }
  const snapshot = {
    id: active.id,
    scrollLeft: active.scrollLeft,
    scrollTop: active.scrollTop,
  };
  if ("selectionStart" in active) {
    snapshot.selectionStart = active.selectionStart;
    snapshot.selectionEnd = active.selectionEnd;
    snapshot.selectionDirection = active.selectionDirection;
  }
  return snapshot;
}

function restoreFocusSnapshot(root, snapshot) {
  if (!snapshot) {
    return;
  }
  const target = root.querySelector(`#${escapeCssIdentifier(snapshot.id)}`);
  if (!(target instanceof HTMLElement)) {
    return;
  }
  target.focus({ preventScroll: true });
  if ("selectionStart" in target && snapshot.selectionStart !== undefined) {
    try {
      target.selectionStart = snapshot.selectionStart;
      target.selectionEnd = snapshot.selectionEnd ?? snapshot.selectionStart;
      if (snapshot.selectionDirection) {
        target.selectionDirection = snapshot.selectionDirection;
      }
    } catch {
      // Ignore selection restore failures for unsupported input types.
    }
  }
  target.scrollLeft = snapshot.scrollLeft ?? 0;
  target.scrollTop = snapshot.scrollTop ?? 0;
}

function escapeCssIdentifier(value) {
  if (globalThis.CSS?.escape) {
    return globalThis.CSS.escape(value);
  }
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

const Fragment = Symbol("microact.fragment");

let rootState = null;
let renderScheduled = false;
let isRendering = false;
let currentInstance = null;
let pendingEffects = [];
const componentInstances = new Map();
const domNodes = new Map();

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
  if (rootState && rootState.root !== root) {
    pruneInstances(() => false);
  }
  rootState = { root, vnode };
  scheduleRender();
}

export function useState(initialValue) {
  return useReducer(
    (value, next) => (typeof next === "function" ? next(value) : next),
    initialValue,
    (value) => (typeof value === "function" ? value() : value),
  );
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
      reconcileChildren(rootState.root, renderNodes(rootState.vnode, "0", seenPaths));
      pruneInstances((path) => seenPaths.has(path));
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

function cleanupInstance(instance) {
  for (const hook of instance.hooks) {
    if (hook.kind === "effect" && typeof hook.cleanup === "function") {
      try {
        hook.cleanup();
      } catch {
        /* Continue cleaning up other components. */
      }
    }
  }
}

function pruneInstances(keepPath) {
  for (const [path, instance] of componentInstances) {
    if (!keepPath(path)) {
      cleanupInstance(instance);
      componentInstances.delete(path);
    }
  }
  for (const [path, record] of domNodes) {
    if (!keepPath(path)) {
      assignRef(record.props?.ref, null);
      domNodes.delete(path);
    }
  }
}

function renderNodes(vnode, path, seenPaths) {
  if (vnode === null || vnode === undefined || typeof vnode === "boolean") return [];
  if (Array.isArray(vnode)) {
    return vnode.flatMap((child, index) => {
      const key = child?.props?.key;
      return renderNodes(
        child,
        `${path}.${key === undefined ? `i${index}` : `k${JSON.stringify(key)}`}`,
        seenPaths,
      );
    });
  }
  const text = typeof vnode === "string" || typeof vnode === "number";
  const type = text ? "#text" : vnode.type;
  const previousType = componentInstances.get(path)?.type ?? domNodes.get(path)?.type;
  if (previousType !== undefined && previousType !== type) {
    // Replacing a parent also unmounts its children, even at otherwise identical paths.
    pruneInstances((candidate) => candidate !== path && !candidate.startsWith(`${path}.`));
  }
  if (typeof vnode.type === "function") {
    let instance = componentInstances.get(path);
    if (!instance) {
      instance = { type: vnode.type, hooks: [], hookIndex: 0 };
      componentInstances.set(path, instance);
    }
    seenPaths.add(path);
    const previous = currentInstance;
    currentInstance = instance;
    instance.hookIndex = 0;
    let rendered;
    try {
      rendered = vnode.type(vnode.props ?? {});
    } finally {
      currentInstance = previous;
    }
    return renderNodes(rendered, `${path}.0`, seenPaths);
  }
  if (vnode.type === Fragment) {
    return renderNodes(vnode.props?.children, `${path}.f`, seenPaths);
  }
  let record = domNodes.get(path);
  if (!record) {
    record = {
      type,
      node: text ? document.createTextNode("") : document.createElement(type),
      props: {},
    };
    domNodes.set(path, record);
  }
  seenPaths.add(path);
  if (text) {
    if (record.node.data !== String(vnode)) record.node.data = String(vnode);
  } else {
    const props = vnode.props ?? {};
    reconcileChildren(record.node, renderNodes(props.children, `${path}.c`, seenPaths));
    updateProps(record.node, record.props, props);
    record.props = props;
  }
  return [record.node];
}

function reconcileChildren(parent, nodes) {
  for (let index = 0; index < nodes.length; index += 1) {
    const current = parent.childNodes[index];
    if (current !== nodes[index]) parent.insertBefore(nodes[index], current ?? null);
  }
  while (parent.childNodes.length > nodes.length) parent.lastChild.remove();
}

function updateProps(element, previous, props) {
  for (const name of new Set([...Object.keys(previous), ...Object.keys(props)])) {
    if (name === "children" || name === "key") continue;
    const value = props[name];
    if (Object.is(previous[name], value)) continue;
    if (name === "ref") {
      assignRef(previous[name], null);
      assignRef(value, element);
    } else if (name.startsWith("on")) {
      element[name.toLowerCase()] = value ?? null;
    } else if (name === "class" || name === "className") {
      element.className = value ?? "";
    } else if (name === "style") {
      for (const key of new Set([
        ...Object.keys(previous.style ?? {}),
        ...Object.keys(value ?? {}),
      ])) {
        element.style[key] = value?.[key] ?? "";
      }
    } else if (name in element && !name.startsWith("aria-")) {
      const next = value ?? (typeof element[name] === "boolean" ? false : "");
      // Avoid resetting caret/selection when the browser already has this value.
      if (element[name] !== next) element[name] = next;
    } else if (
      value === null ||
      value === undefined ||
      (value === false && !name.startsWith("aria-"))
    ) {
      element.removeAttribute(name);
    } else {
      element.setAttribute(name, value === true && !name.startsWith("aria-") ? "" : String(value));
    }
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

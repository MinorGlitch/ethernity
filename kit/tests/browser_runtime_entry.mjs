import { jsx, render, useState, useRef, useEffect } from "../lib/microact/core.js";

async function checkRenderer() {
  const root = document.createElement("div");
  document.body.replaceChildren(root);
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  const check = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  let update;
  let mounts = 0;
  let cleanups = 0;
  let childRef;
  function Child() {
    const ref = useRef(null);
    childRef = ref;
    useEffect(() => {
      mounts += 1;
      return () => {
        cleanups += 1;
      };
    }, []);
    return jsx("video", { ref });
  }
  function App() {
    const [state, setState] = useState({ count: 0, show: true, order: ["a", "b"], tag: "section" });
    update = setState;
    return jsx(state.tag, {
      children: [
        jsx("button", {
          id: "counter",
          disabled: state.count === 2,
          onClick: () => setState({ ...state, count: state.count + 1 }),
          children: String(state.count),
        }),
        state.show ? jsx(Child, {}) : null,
        jsx("ul", { children: state.order.map((key) => jsx("li", { children: key }, key)) }),
      ],
    });
  }
  render(jsx(App, {}), root);
  await tick();
  const button = root.querySelector("button");
  const video = childRef.current;
  const items = Array.from(root.querySelectorAll("li"));
  button.focus();
  button.click();
  await tick();
  check(
    root.querySelector("button") === button && document.activeElement === button,
    "Stable button lost identity or focus",
  );
  check(button.textContent === "1" && !button.disabled, "First handler failed");
  button.click();
  await tick();
  check(button.textContent === "2" && button.disabled, "Handler was stale or duplicated");
  check(
    childRef.current === video && mounts === 1 && cleanups === 0,
    "Child remounted on parent update",
  );
  update((state) => ({ ...state, count: 0, order: ["b", "a"] }));
  await tick();
  check(!button.disabled && button.textContent === "0", "Boolean property was not cleared");
  check(root.querySelectorAll("li")[0] === items[1], "Keyed child was recreated");
  update((state) => ({ ...state, show: false }));
  await tick();
  check(childRef.current === null && cleanups === 1, "Unmount did not clear ref and effect");
  update((state) => ({ ...state, show: true }));
  await tick();
  check(childRef.current !== video && mounts === 2, "Remount reused an unmounted child");
  update((state) => ({ ...state, tag: "article" }));
  await tick();
  check(mounts === 3 && cleanups === 2, "Replacing a DOM parent did not unmount its children");
  function Replacement() {
    return jsx("article", { children: [null, jsx(Child, {}), null] });
  }
  render(jsx(Replacement, {}), root);
  await tick();
  check(mounts === 4 && cleanups === 3, "Replacing a component retained its previous children");
  render(null, root);
  await tick();
  check(cleanups === 4 && root.childNodes.length === 0, "Root unmount failed");
}

checkRenderer().then(
  () => {
    document.body.textContent = "renderer-ok";
  },
  (error) => {
    document.body.textContent = `renderer-error: ${error.stack ?? error}`;
  },
);

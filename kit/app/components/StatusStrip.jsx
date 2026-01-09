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

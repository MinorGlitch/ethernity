import { useState } from "microact/hooks";

export function useCollectorInput({ value, onChange, onAdd, onScannedPayload, scannedItemLabel }) {
  const [pasteHint, setPasteHint] = useState("");

  const handlePaste = (event) => {
    const lines = payloadLines(event.clipboardData?.getData("text/plain"));
    if (lines.length) {
      setPasteHint(`Pasted ${lines.length} line(s). Click Add.`);
    }
  };
  const handleChange = (event) => {
    setPasteHint("");
    onChange(event);
  };
  const handleAdd = () => {
    setPasteHint("");
    onAdd();
  };
  const handleScanPayload = (scannedPayload) => {
    const hasBytes = scannedPayload?.bytes instanceof Uint8Array && scannedPayload.bytes.length > 0;
    if (hasBytes && typeof onScannedPayload === "function") {
      onScannedPayload(scannedPayload);
      setPasteHint(`Scanned 1 ${scannedItemLabel}. Added automatically.`);
      return;
    }

    const lines = payloadLines(scannedPayload?.text);
    if (!lines.length) {
      setPasteHint("Scanned QR was empty.");
      return;
    }
    const prefix = value && !value.endsWith("\n") ? "\n" : "";
    onChange({ currentTarget: { value: `${value ?? ""}${prefix}${lines.join("\n")}` } });
    setPasteHint(`Scanned ${lines.length} line(s). Click Add.`);
  };

  return { pasteHint, handlePaste, handleChange, handleAdd, handleScanPayload };
}

function payloadLines(value) {
  return String(value ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

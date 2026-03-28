export function selectedVariants(requested = "both") {
  const normalized = requested.toLowerCase();
  if (normalized === "both") {
    return [
      { id: "lean", bundleName: "recovery_kit.bundle.html", scannerMode: "none" },
      { id: "scanner", bundleName: "recovery_kit.scanner.bundle.html", scannerMode: "jsqr" },
    ];
  }
  if (normalized === "lean") {
    return [{ id: "lean", bundleName: "recovery_kit.bundle.html", scannerMode: "none" }];
  }
  if (normalized === "scanner") {
    return [{ id: "scanner", bundleName: "recovery_kit.scanner.bundle.html", scannerMode: "jsqr" }];
  }
  throw new Error("ETHERNITY_KIT_VARIANTS must be one of: both, lean, scanner");
}

export function scannerHookPathForMode(scannerMode, scannerHookLeanPath, scannerHookJsqrPath) {
  return scannerMode === "jsqr" ? scannerHookJsqrPath : scannerHookLeanPath;
}

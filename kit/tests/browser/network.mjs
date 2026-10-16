async function setOfflineAndWaitForEvent(page, offline) {
  await page.evaluate(
    (eventName) => {
      window.networkChangeObserved = false;
      window.addEventListener(
        eventName,
        () => {
          window.networkChangeObserved = true;
        },
        { once: true },
      );
    },
    offline ? "offline" : "online",
  );
  await page.context().setOffline(offline);
  await page.waitForFunction(() => window.networkChangeObserved);
}

export async function checkOfflineTransitions(page) {
  await setOfflineAndWaitForEvent(page, true);
  const input = page.locator("#payload-text");
  await input.fill("offline draft");
  await setOfflineAndWaitForEvent(page, false);
  await page.locator("#offline-guard-title").waitFor({ state: "visible" });
  await page.getByRole("button", { name: "Use while online", exact: true }).click();
  await input.waitFor({ state: "visible" });
  if ((await input.inputValue()) !== "offline draft") {
    throw new Error("Network changes discarded recovery input");
  }
  await setOfflineAndWaitForEvent(page, true);
  await setOfflineAndWaitForEvent(page, false);
  await page.locator("#offline-guard-title").waitFor({ state: "visible" });
  await setOfflineAndWaitForEvent(page, true);
  await input.waitFor({ state: "visible" });
  if ((await input.inputValue()) !== "offline draft") {
    throw new Error("Automatic offline entry discarded recovery input");
  }
}

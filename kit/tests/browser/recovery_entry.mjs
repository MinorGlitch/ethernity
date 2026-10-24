export async function checkRecoveryEntry(page) {
  const originalViewport = page.viewportSize();
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    await page.evaluate(() => {
      document.getElementById("use-online").click();
      const input = document.getElementById("payload-text");
      input.value = `01. ${"ybnr fghj kmnp 1934 ".repeat(20)}\n02. ${"kmnp ".repeat(30)}\n03. ybnr\n`;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await page.evaluate(() => new Promise(requestAnimationFrame));
    await page.evaluate(() => new Promise(requestAnimationFrame));
    await page.evaluate(() => {
      const check = (condition, message) => {
        if (!condition) throw new Error(message);
      };
      const input = document.getElementById("payload-text");
      const editor = input.parentElement;
      const content = editor.querySelector(".recovery-mirror > div");
      const first = editor.querySelector(".recovery-line-text").getBoundingClientRect();
      const rect = input.getBoundingClientRect();
      const style = getComputedStyle(input);
      check(
        Math.abs(first.left - rect.left - parseFloat(style.paddingLeft)) < 1,
        "Highlight text does not align with the caret horizontally",
      );
      check(
        Math.abs(first.top - rect.top - parseFloat(style.paddingTop)) < 1,
        "Highlight text does not align with the caret vertically",
      );
      check(
        Math.abs(content.offsetHeight - input.scrollHeight) <= 1,
        `Wrapped highlights drift: ${content.offsetHeight} vs ${input.scrollHeight}`,
      );
      check(
        editor.querySelectorAll(".recovery-line-number").length === 4,
        "Soft wrapping changed logical line numbers",
      );
      input.scrollTop = input.scrollHeight;
      input.dispatchEvent(new Event("scroll"));
      check(
        content.style.transform === `translateY(${-input.scrollTop}px)`,
        "Highlights did not follow scrolling",
      );
      document.getElementById("reset").click();
    });
  }
  if (originalViewport) await page.setViewportSize(originalViewport);
}

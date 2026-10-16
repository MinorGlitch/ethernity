import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { kitDir } from "./support.mjs";

export async function checkScannerImages(page) {
  const frames = [];
  for (const name of ["v1-main", "v1-text", "v2-shard"]) {
    const png = await readFile(resolve(kitDir, "tests", "fixtures", `scanner-${name}.png`));
    frames.push({ name, image: `data:image/png;base64,${png.toString("base64")}` });
  }
  const text = (
    await readFile(
      resolve(
        kitDir,
        "..",
        "tests",
        "fixtures",
        "v1_0",
        "golden",
        "base64",
        "file_no_shard",
        "main_payloads.txt",
      ),
      "utf8",
    )
  ).split(/\r?\n/)[0];
  await page.evaluate(
    async ({ frames, text }) => {
      const originalMedia = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
      const originalPlay = HTMLMediaElement.prototype.play;
      const originalDraw = CanvasRenderingContext2D.prototype.drawImage;
      let image;
      let stops = 0;
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          async getUserMedia() {
            const stream = new MediaStream();
            stream.getTracks = () => [
              {
                stop() {
                  stops += 1;
                },
              },
            ];
            return stream;
          },
        },
      });
      HTMLMediaElement.prototype.play = async function () {
        Object.defineProperty(this, "videoWidth", { configurable: true, value: image.width });
        Object.defineProperty(this, "videoHeight", { configurable: true, value: image.height });
      };
      CanvasRenderingContext2D.prototype.drawImage = function (source, ...args) {
        return originalDraw.call(
          this,
          source instanceof HTMLVideoElement ? image : source,
          ...args,
        );
      };
      const check = (condition, message) => {
        if (!condition) throw new Error(message);
      };
      try {
        for (const frame of frames) {
          document.getElementById("reset").click();
          image = new Image();
          image.src = frame.image;
          await image.decode();
          const panel = document.getElementById(
            frame.name === "v2-shard" ? "sheets-scanner" : "backup-scanner",
          );
          const video = panel.querySelector("video");
          panel.querySelector("button").click();
          for (
            let attempt = 0;
            attempt < 100 && !panel.textContent.includes("Scan complete");
            attempt++
          ) {
            await new Promise((resolve) => setTimeout(resolve, 20));
          }
          check(
            panel.textContent.includes("Scan complete"),
            `Could not scan ${frame.name}: ${panel.textContent}`,
          );
          check(
            !video.srcObject && panel.querySelector(".scan-preview").hidden,
            "Completed scan kept the camera running",
          );
          if (frame.name === "v1-text") {
            check(
              document.getElementById("payload-text").value === text,
              "Base64 QR text was changed",
            );
            document.getElementById("backup-add").click();
          }
          await new Promise((resolve) => setTimeout(resolve, 0));
          const status = document.getElementById(
            frame.name === "v2-shard" ? "sheets-status" : "backup-status",
          );
          check(
            !status.hidden && !status.querySelector(".status.error"),
            `Scanned ${frame.name} was rejected: ${status.textContent}`,
          );
          if (frame.name === "v2-shard")
            check(status.textContent.includes("1 of 2 needed"), "Shard was not collected");
        }
        check(stops === frames.length, "Scanner leaked or stopped a camera more than once");
        document.getElementById("reset").click();
      } finally {
        HTMLMediaElement.prototype.play = originalPlay;
        CanvasRenderingContext2D.prototype.drawImage = originalDraw;
        if (originalMedia) Object.defineProperty(navigator, "mediaDevices", originalMedia);
        else delete navigator.mediaDevices;
      }
    },
    { frames, text },
  );
}

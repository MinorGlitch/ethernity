import { mkdir, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "../../kit/node_modules/playwright/index.mjs";

const OUT = new URL("../../build/readme-logo/paper-assembly/", import.meta.url);
const WIDTH = 640,
  HEIGHT = 338,
  SUPERSAMPLE = 4,
  FRAMES = 250,
  FPS = 25;
const gold = "#e2b85f",
  light = "#ebc36a",
  shade = "#d9ad57",
  back = "#34372f";
const root = {
  points: [
    [394, 312],
    [630, 548],
    [630, 712],
    [394, 484],
  ],
  color: gold,
  layer: 4,
};
const pieces = [
  {
    points: [
      [306, 398],
      [394, 312],
      [394, 484],
    ],
    hinge: [
      [394, 312],
      [394, 484],
    ],
    color: back,
    start: 0,
    duration: 0.35,
    layer: 3,
  },
  {
    points: [
      [88, 440],
      [218, 312],
      [394, 312],
      [176, 512],
      [88, 592],
    ],
    hinge: [
      [306, 398],
      [394, 312],
    ],
    color: light,
    start: 0.35,
    duration: 0.75,
    layer: 1,
  },
  {
    points: [
      [88, 592],
      [176, 512],
      [306, 632],
      [394, 712],
      [218, 712],
    ],
    hinge: [
      [88, 592],
      [176, 512],
    ],
    color: shade,
    start: 1.1,
    duration: 0.75,
    layer: 2,
  },
  {
    points: [
      [306, 632],
      [512, 428.543],
      [512, 597.437],
      [394, 712],
    ],
    hinge: [
      [306, 632],
      [394, 712],
    ],
    color: gold,
    start: 1.85,
    duration: 0.65,
    layer: 0,
    tuck: true,
  },
  {
    points: [
      [630, 548],
      [712, 632],
      [630, 712],
    ],
    hinge: [
      [630, 548],
      [630, 712],
    ],
    color: back,
    start: 0.16,
    duration: 0.35,
    layer: 3,
  },
  {
    points: [
      [936, 592],
      [806, 712],
      [630, 712],
      [844, 512],
    ],
    hinge: [
      [630, 712],
      [712, 632],
    ],
    color: shade,
    start: 0.51,
    duration: 0.75,
    layer: 2,
  },
  {
    points: [
      [806, 312],
      [936, 440],
      [936, 592],
      [844, 512],
      [712, 398],
    ],
    hinge: [
      [936, 592],
      [844, 512],
    ],
    color: light,
    start: 1.26,
    duration: 0.75,
    layer: 1,
  },
  {
    points: [
      [512, 428.543],
      [630, 312],
      [806, 312],
      [512, 597.437],
    ],
    hinge: [
      [806, 312],
      [712, 398],
    ],
    color: gold,
    start: 2.01,
    duration: 0.65,
    layer: 0,
    tuck: true,
  },
];
const add = (a, b) => a.map((x, i) => x + b[i]);
const sub = (a, b) => a.map((x, i) => x - b[i]);
const scale = (a, t) => a.map((v) => v * t);
const dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const rotate = (p, a, b, angle) => {
  const v = sub(p, a),
    delta = sub(b, a),
    axis = scale(delta, 1 / Math.hypot(...delta));
  return add(
    a,
    add(
      add(scale(v, Math.cos(angle)), scale(cross(axis, v), Math.sin(angle))),
      scale(axis, dot(axis, v) * (1 - Math.cos(angle))),
    ),
  );
};
const ease = (t) => t * t * t * (10 + t * (-15 + 6 * t));
const clamp = (t) => Math.max(0, Math.min(1, t));
function unfoldTime(time) {
  if (time < 1) return 0;
  if (time < 6) return Math.min(3, time - 1);
  return Math.max(0, 3 - (time - 6));
}
function rootProgress(time) {
  if (time < 1) return clamp((time - 0.16) / 0.8);
  if (time < 9) return 1;
  return clamp(1 - (time - 9) / 0.8);
}
function mesh(time) {
  const opening = rootProgress(time);
  if (opening === 0) return [];
  const angle = ((1 - ease(opening)) * Math.PI) / 2;
  const vertices = root.points.map((p) => rotate([...p, 0], [394, 398, 0], [630, 630, 0], angle));
  const faces = [
    { vertices, color: root.color, layer: root.layer, light: 0.76 + 0.24 * Math.cos(angle) },
  ];
  const progress = unfoldTime(time);
  for (const piece of pieces) {
    const t = Math.max(0, Math.min(1, (progress - piece.start) / piece.duration));
    if (t === 0) continue;
    const angle = ((1 - ease(t)) * Math.PI) / 2;
    const a = [...piece.hinge[0], 0],
      b = [...piece.hinge[1], 0];
    const center = piece.points.reduce(
      (s, p) => [s[0] + p[0] / piece.points.length, s[1] + p[1] / piece.points.length, 0],
      [0, 0, 0],
    );
    const side = Math.sign(cross(sub(b, a), sub(center, a))[2]) || 1;
    const sign = side * (piece.tuck ? -1 : 1);
    const vertices = piece.points.map((p) => rotate([...p, 0], a, b, angle * sign));
    faces.push({
      vertices,
      color: piece.color,
      layer: piece.layer,
      light: 0.76 + 0.24 * Math.cos(angle),
    });
  }
  const data = [];
  for (const face of faces) {
    const color = [1, 3, 5].map(
      (i) => (parseInt(face.color.slice(i, i + 2), 16) / 255) * face.light,
    );
    for (let k = 1; k < face.vertices.length - 1; k++)
      for (const p of [face.vertices[0], face.vertices[k], face.vertices[k + 1]]) {
        data.push(
          (2 * (p[0] - 512)) / ((524 * WIDTH) / HEIGHT),
          1 - (2 * (p[1] - 250)) / 524,
          -(p[2] + face.layer * 0.15) / 1000,
          ...color,
        );
      }
  }
  return data;
}
await mkdir(new URL("frames/", OUT), { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.setContent(
    `<canvas width="${WIDTH * SUPERSAMPLE}" height="${HEIGHT * SUPERSAMPLE}"></canvas>`,
  );
  await page.evaluate(
    ({ width, height }) => {
      const canvas = document.querySelector("canvas");
      const gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        preserveDrawingBuffer: true,
        // Multisample edge colors already include coverage. Unpremultiply them when
        // exporting, otherwise translucent gold edges turn dark on light backgrounds.
        premultipliedAlpha: true,
      });
      if (!gl) throw new Error("WebGL is unavailable");
      const compile = (kind, source) => {
        const shader = gl.createShader(kind);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS))
          throw new Error(gl.getShaderInfoLog(shader));
        return shader;
      };
      const program = gl.createProgram();
      gl.attachShader(
        program,
        compile(
          gl.VERTEX_SHADER,
          "attribute vec3 position; attribute vec3 color; varying vec3 paint; void main(){gl_Position=vec4(position,1.0);paint=color;}",
        ),
      );
      gl.attachShader(
        program,
        compile(
          gl.FRAGMENT_SHADER,
          "precision mediump float; varying vec3 paint; void main(){gl_FragColor=vec4(paint,1.0);}",
        ),
      );
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS))
        throw new Error(gl.getProgramInfoLog(program));
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      for (const [name, offset] of [
        ["position", 0],
        ["color", 12],
      ]) {
        const location = gl.getAttribLocation(program, name);
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, 3, gl.FLOAT, false, 24, offset);
      }
      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.clearColor(0, 0, 0, 0);
      gl.viewport(0, 0, canvas.width, canvas.height);
      const output = document.createElement("canvas");
      output.width = width;
      output.height = height;
      const context = output.getContext("2d");
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = "high";
      window.renderLogo = (data) => {
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW);
        gl.drawArrays(gl.TRIANGLES, 0, data.length / 6);
        // Canvas resizing preserves edge coverage in premultiplied color space.
        context.clearRect(0, 0, width, height);
        context.drawImage(canvas, 0, 0, width, height);
        return output.toDataURL("image/png").split(",")[1];
      };
    },
    { width: WIDTH, height: HEIGHT },
  );
  for (let i = 0; i < FRAMES; i++) {
    // Begin and end on transparent frames; the strip opens before the attached folds.
    const png = await page.evaluate((data) => window.renderLogo(data), mesh(i / FPS));
    await writeFile(
      new URL(`frames/${String(i).padStart(3, "0")}.png`, OUT),
      Buffer.from(png, "base64"),
    );
  }
} finally {
  await browser.close();
}
// GIF's binary transparency destroys antialiasing. APNG preserves full RGBA
// colors and the original frame timing without a background matte or palette.
const result = spawnSync(
  "ffmpeg",
  [
    "-v",
    "error",
    "-y",
    "-framerate",
    String(FPS),
    "-i",
    `${fileURLToPath(new URL("frames/", OUT))}%03d.png`,
    "-frames:v",
    String(FRAMES),
    "-c:v",
    "apng",
    "-pix_fmt",
    "rgba",
    "-compression_level",
    "9",
    "-plays",
    "0",
    "-f",
    "apng",
    fileURLToPath(new URL("ribbon.png", OUT)),
  ],
  { stdio: "inherit" },
);
if (result.error) throw result.error;
if (result.status !== 0) throw new Error("ffmpeg failed");

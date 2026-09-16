/**
 * Operant desktop: an Electron window around the local Operant server.
 *
 * On launch it starts `operant serve` as a child process on a free local
 * port with a fresh bearer token, serves the built web UI from it, and signs
 * the UI in with that token. Because the server is a child of the app, macOS
 * asks for Accessibility and Screen Recording for the app itself, and the
 * server drives the screen in-process (no separate driver daemon). Quitting
 * the app stops the server.
 */

import { ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:net";
import path from "node:path";

import { app, BrowserWindow, dialog, shell } from "electron";

const TOKEN_KEY = "operant.token";
const HEALTH_TIMEOUT_MS = 90_000;
const HEALTH_POLL_MS = 500;
const WINDOW_WIDTH = 1320;
const WINDOW_HEIGHT = 880;
const BACKGROUND_COLOR = "#111827";
const TOKEN_BYTES = 24;
const RECORD_FRAME_MS = 700;
const DEMO_SCRIPT_DELAY_MS = 3000;
const SNAPSHOT_DELAY_MS = 6000;

// desktop/dist/main.js -> repository root.
const repoRoot = path.resolve(__dirname, "..", "..");

let server: ChildProcess | null = null;
let quitting = false;

function serverLogPath(): string {
  return path.join(app.getPath("logs"), "desktop-server.log");
}

function fail(message: string, title = "Operant"): void {
  if (quitting) return;
  quitting = true;
  dialog.showErrorBox(title, message);
  app.quit();
}

function describeExit(code: number | null, signal: NodeJS.Signals | null): string {
  return code === null ? `signal ${signal ?? "unknown"}` : `code ${code}`;
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      const port = typeof address === "object" && address ? address.port : 0;
      probe.close(() => resolve(port));
    });
  });
}

function startServer(port: number, token: string): ChildProcess {
  const logPath = serverLogPath();
  mkdirSync(path.dirname(logPath), { recursive: true });
  const log = createWriteStream(logPath, { flags: "a" });
  // GUI apps on macOS do not inherit the shell PATH; add the usual uv homes.
  const extraPath = [
    path.join(process.env.HOME ?? "", ".local", "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
  ].join(path.delimiter);
  const child = spawn("uv", ["run", "operant", "serve", "--port", String(port)], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PATH: `${extraPath}${path.delimiter}${process.env.PATH ?? ""}`,
      OPERANT_SERVER__AUTH_TOKEN: token,
      OPERANT_SERVER__STATIC_DIR: path.join(repoRoot, "web", "dist"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout?.pipe(log);
  child.stderr?.pipe(log);
  child.on("error", (err) => {
    server = null;
    fail(`Could not start the local server with uv: ${err.message}. Is uv installed?`);
  });
  child.on("exit", (code, signal) => {
    server = null;
    fail(
      `The local server exited (${describeExit(code, signal)}). See ${logPath}.`,
      "Operant server stopped",
    );
  });
  return child;
}

async function waitHealthy(base: string): Promise<boolean> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  // `server` is cleared when the child exits, so a crash stops the wait early.
  while (server !== null && Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) return true;
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, HEALTH_POLL_MS));
  }
  return false;
}

function splash(): string {
  const html = `<!doctype html><meta charset="utf-8"><title>Operant</title>
    <body style="margin:0;height:100vh;display:grid;place-items:center;
      font:15px -apple-system,system-ui,sans-serif;background:${BACKGROUND_COLOR};color:#e5e7eb">
      <div>Starting Operant&hellip;</div></body>`;
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}

async function signIn(window: BrowserWindow, base: string, token: string): Promise<void> {
  // The UI keeps its bearer token in localStorage, which is per origin: set
  // it from a same-origin page before the UI's own code runs and redirects.
  await window.loadURL(`${base}/healthz`);
  await window.webContents.executeJavaScript(
    `localStorage.setItem(${JSON.stringify(TOKEN_KEY)}, ${JSON.stringify(token)})`,
  );
}

async function launch(): Promise<void> {
  const webIndex = path.join(repoRoot, "web", "dist", "index.html");
  if (!existsSync(webIndex)) {
    fail("The web UI is not built. Run: pnpm --dir web build");
    return;
  }
  const window = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    title: "Operant",
    backgroundColor: BACKGROUND_COLOR,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  // Links to other sites open in the default browser, not in the app.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });
  await window.loadURL(splash());

  // Scripted demos pin the port and token so a driver can use the same
  // server the window shows; normal launches pick fresh ones.
  const port = Number(process.env.OPERANT_DESKTOP_PORT) || (await freePort());
  const token = process.env.OPERANT_DESKTOP_TOKEN || randomBytes(TOKEN_BYTES).toString("hex");
  const base = `http://127.0.0.1:${port}`;
  const origin = new URL(base).origin;
  // In-page navigation must stay on the local server; anything else opens in the browser.
  window.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin === origin) return;
    event.preventDefault();
    if (/^https?:/.test(url)) void shell.openExternal(url);
  });
  server = startServer(port, token);
  if (!(await waitHealthy(base))) {
    fail(`The local server did not start in time. See ${serverLogPath()}.`);
    return;
  }
  await signIn(window, base, token);
  await window.loadURL(base);
  const record = process.env.OPERANT_DESKTOP_RECORD;
  if (record) {
    // For the README demo: save the window every RECORD_FRAME_MS as numbered frames.
    mkdirSync(record, { recursive: true });
    let frame = 0;
    const timer = setInterval(() => {
      window.webContents
        .capturePage()
        .then((image) => {
          const name = `frame-${String(frame++).padStart(5, "0")}.png`;
          writeFileSync(path.join(record, name), image.toPNG());
        })
        .catch(() => undefined);
    }, RECORD_FRAME_MS);
    window.on("closed", () => clearInterval(timer));
  }
  const script = process.env.OPERANT_DESKTOP_SCRIPT;
  if (script) {
    // For recorded demos: drive the UI the way a person would, in the page.
    setTimeout(() => {
      window.webContents
        .executeJavaScript(readFileSync(script, "utf8"))
        .catch((err: unknown) => console.error("demo script failed:", err));
    }, DEMO_SCRIPT_DELAY_MS);
  }
  const snapshot = process.env.OPERANT_DESKTOP_SNAPSHOT;
  if (snapshot) {
    // For docs and checks: save what the window shows once it settles.
    setTimeout(() => {
      window.webContents
        .capturePage()
        .then((image) => writeFileSync(snapshot, image.toPNG()))
        .catch((err: unknown) => console.error("snapshot failed:", err));
    }, SNAPSHOT_DELAY_MS);
  }
}

function stopServer(): void {
  quitting = true;
  if (server && server.exitCode === null) server.kill("SIGTERM");
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [window] = BrowserWindow.getAllWindows();
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app
    .whenReady()
    .then(launch)
    .catch((err: unknown) => {
      fail(`Operant failed to start: ${err instanceof Error ? err.message : String(err)}`);
    });
  app.on("before-quit", stopServer);
  // Ctrl+C or a kill from a terminal must not leave the server running.
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => app.quit());
  }
  app.on("window-all-closed", () => app.quit());
}

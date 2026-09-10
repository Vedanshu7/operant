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
import { createWriteStream, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";

import { app, BrowserWindow, dialog, shell } from "electron";

const TOKEN_KEY = "operant.token";
const HEALTH_TIMEOUT_MS = 90_000;

// desktop/dist/main.js -> repository root.
const repoRoot = path.resolve(__dirname, "..", "..");

let server: ChildProcess | null = null;
let quitting = false;

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
  const logDir = path.join(repoRoot, "state");
  mkdirSync(logDir, { recursive: true });
  const log = createWriteStream(path.join(logDir, "desktop-server.log"), { flags: "a" });
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
  child.on("exit", (code) => {
    server = null;
    if (!quitting) {
      dialog.showErrorBox(
        "Operant server stopped",
        `The local server exited (code ${code}). See state/desktop-server.log.`,
      );
      app.quit();
    }
  });
  return child;
}

async function waitHealthy(base: string): Promise<boolean> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${base}/healthz`);
      if (response.ok) return true;
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

function splash(): string {
  const html = `<!doctype html><meta charset="utf-8"><title>Operant</title>
    <body style="margin:0;height:100vh;display:grid;place-items:center;
      font:15px -apple-system,system-ui,sans-serif;background:#111827;color:#e5e7eb">
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
    dialog.showErrorBox("Operant", "The web UI is not built. Run: pnpm --dir web build");
    app.quit();
    return;
  }
  const window = new BrowserWindow({
    width: 1320,
    height: 880,
    title: "Operant",
    backgroundColor: "#111827",
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
  const token = process.env.OPERANT_DESKTOP_TOKEN || randomBytes(24).toString("hex");
  const base = `http://127.0.0.1:${port}`;
  server = startServer(port, token);
  if (!(await waitHealthy(base))) {
    dialog.showErrorBox(
      "Operant",
      "The local server did not start in time. See state/desktop-server.log.",
    );
    app.quit();
    return;
  }
  await signIn(window, base, token);
  await window.loadURL(base);
  const record = process.env.OPERANT_DESKTOP_RECORD;
  if (record) {
    // For the README demo: save the window every 700 ms as numbered frames.
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
    }, 700);
    window.on("closed", () => clearInterval(timer));
  }
  const snapshot = process.env.OPERANT_DESKTOP_SNAPSHOT;
  if (snapshot) {
    // For docs and checks: save what the window shows once it settles.
    setTimeout(() => {
      window.webContents
        .capturePage()
        .then((image) => writeFileSync(snapshot, image.toPNG()))
        .catch((err: unknown) => console.error("snapshot failed:", err));
    }, 6000);
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
  app.whenReady().then(launch);
  app.on("before-quit", stopServer);
  // Ctrl+C or a kill from a terminal must not leave the server running.
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => app.quit());
  }
  app.on("window-all-closed", () => app.quit());
}

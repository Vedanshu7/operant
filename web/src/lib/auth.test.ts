/// <reference types="node" />
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { TOKEN_KEY } from "./auth";

describe("TOKEN_KEY", () => {
  it("matches the key the desktop app signs the UI in with", () => {
    const desktopMain = readFileSync(
      path.resolve(__dirname, "../../../desktop/src/main.ts"),
      "utf8",
    );
    expect(desktopMain).toContain(`const TOKEN_KEY = ${JSON.stringify(TOKEN_KEY)};`);
  });
});

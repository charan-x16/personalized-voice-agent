// Optional public-surface visual smoke check. Requires Next.js on :3000 with
// Clerk development keys configured. Authenticated flows should use Clerk's
// Testing Tokens or a manually signed-in browser profile.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const output = path.resolve("artifacts/frontend-review");
const appOrigin = process.env.BROWSER_REVIEW_ORIGIN || "http://localhost:3000";
await mkdir(output, { recursive: true });
const profile = await mkdtemp(path.join(output, "chrome-"));
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [
  "--headless=new",
  "--no-first-run",
  "--no-default-browser-check",
  "--remote-debugging-port=0",
  `--user-data-dir=${profile}`,
  "about:blank",
], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });

let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    let log = "";
    const timer = setTimeout(() => reject(new Error("Chrome startup timed out")), 20_000);
    chrome.on("error", reject);
    chrome.stderr.on("data", (chunk) => {
      log += chunk.toString();
      const match = log.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });

  let sequence = 0;
  let sessionId;
  const pending = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    const callback = pending.get(message.id);
    if (!callback) return;
    pending.delete(message.id);
    if (message.error) callback.reject(message.error);
    else callback.resolve(message.result);
  };

  function cdp(method, params = {}, scoped = true) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`CDP timed out: ${method}`));
      }, 45_000);
      pending.set(id, {
        resolve: (result) => { clearTimeout(timer); resolve(result); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      socket.send(JSON.stringify({ id, method, params, ...(scoped && sessionId ? { sessionId } : {}) }));
    });
  }

  const target = await cdp("Target.createTarget", { url: "about:blank" });
  ({ sessionId } = await cdp("Target.attachToTarget", { targetId: target.targetId, flatten: true }));
  await cdp("Page.enable");
  await cdp("Runtime.enable");

  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  }

  async function waitFor(expression) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      try {
        if (await evaluate(`Boolean(${expression})`)) return;
      } catch {
        // Navigation can replace the execution context between polls.
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    throw new Error(`Timed out: ${expression}`);
  }

  async function visit(route) {
    await cdp("Page.navigate", { url: new URL(route, appOrigin).href });
    await waitFor(`location.pathname === ${JSON.stringify(route)} && document.querySelector('h1') && document.readyState === 'complete'`);
    if (route.startsWith("/sign-")) {
      await waitFor("document.querySelector('input') || document.body.innerText.includes('Continue')");
    }
    await evaluate("document.fonts.ready.then(() => true)");
  }

  async function capture(name, width, height) {
    await cdp("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await new Promise((resolve) => setTimeout(resolve, 350));
    const scrollWidth = await evaluate("document.documentElement.scrollWidth");
    assert.ok(scrollWidth <= width + 1, `${name}: horizontal document overflow`);
    const shot = await cdp("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    await writeFile(path.join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
  }

  for (const route of ["/", "/sign-in", "/sign-up"]) {
    await visit(route);
    const name = route === "/" ? "landing" : route.slice(1);
    await capture(`${name}-desktop`, 1440, 1000);
    await capture(`${name}-mobile`, 390, 844);
  }

  assert.ok(await evaluate("document.body.innerText.includes('Start with Svara.')"));
  await cdp("Page.navigate", { url: new URL("/dashboard", appOrigin).href });
  await waitFor("location.pathname.startsWith('/sign-in')");
  console.log(`Passed public Clerk surface review. Screenshots saved to ${output}`);
} finally {
  socket?.close();
  if (chrome.exitCode === null) {
    chrome.kill();
    await Promise.race([
      once(chrome, "exit"),
      new Promise((resolve) => setTimeout(resolve, 5_000)),
    ]);
  }
  await rm(profile, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 200,
  });
}

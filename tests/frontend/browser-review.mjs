// Optional local visual smoke check. Requires a separate, disposable demo API on :8100
// and Next.js on :3100 (API_BASE_URL=http://127.0.0.1:8100,
// APP_ORIGIN=http://127.0.0.1:3100).
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";

const output = path.resolve("artifacts/frontend-review");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(path.join(output, "chrome-"));
const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [
  "--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
  "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank",
], { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    let log = "";
    const timer = setTimeout(() => reject(new Error("Chrome startup timed out")), 20000);
    chrome.on("error", reject);
    chrome.stderr.on("data", (chunk) => {
      log += chunk.toString();
      const match = log.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  let sessionId;
  const pending = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    const callback = pending.get(message.id);
    if (callback) {
      pending.delete(message.id);
      if (message.error) callback.reject(message.error);
      else callback.resolve(message.result);
    }
  };
  function cdp(method, params = {}, scoped = true) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timed out: ${method}`)); }, 45000);
      pending.set(id, { resolve: result => { clearTimeout(timer); resolve(result); }, reject: error => { clearTimeout(timer); reject(error); } });
      socket.send(JSON.stringify({ id, method, params, ...(scoped && sessionId ? { sessionId } : {}) }));
    });
  }
  const target = await cdp("Target.createTarget", { url: "about:blank" });
  ({ sessionId } = await cdp("Target.attachToTarget", { targetId: target.targetId, flatten: true }));
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  async function evaluate(expression) {
    const response = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  }
  async function waitFor(expression) {
    for (let attempt = 0; attempt < 100; attempt++) {
      try { if (await evaluate(`Boolean(${expression})`)) return; } catch { /* Navigation replaced the context. */ }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    console.log("Page at timeout", await evaluate("JSON.stringify({path:location.pathname,text:document.body.innerText.slice(0,1800),links:[...document.querySelectorAll('a')].map(a=>a.getAttribute('href'))})"));
    throw new Error(`Timed out: ${expression}`);
  }
  async function visit(route) {
    console.log(`Visiting ${route}`);
    await cdp("Page.navigate", { url: `http://127.0.0.1:3100${route}` });
    await waitFor(`location.pathname === ${JSON.stringify(route.split("?")[0])} && document.querySelector('h1') && document.readyState === 'complete'`);
    await evaluate("document.fonts.ready.then(() => true)");
  }
  async function capture(name, width, height = 900) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await new Promise((resolve) => setTimeout(resolve, 250));
    const measurements = await evaluate(`({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      heading: getComputedStyle(document.querySelector('h1')).fontSize,
      inputs: [...document.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=checkbox]), textarea, select')].map(e => ({size:getComputedStyle(e).fontSize,width:e.getBoundingClientRect().width})),
      overflow: [...document.querySelectorAll('main *')].filter(e => { const r=e.getBoundingClientRect(); return r.width>0 && (r.right>innerWidth+1 || r.left < -1) && getComputedStyle(e).position !== 'fixed'; }).slice(0,12).map(e=>({tag:e.tagName,cls:e.className}))
    })`);
    console.log(name, JSON.stringify(measurements));
    assert.ok(measurements.scrollWidth <= width + 1, `${name}: horizontal document overflow`);
    const shot = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(path.join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
  }
  await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  if (!process.argv.includes("--draft-only")) {
  await visit("/");
  await capture("landing-desktop", 1440, 1000);
  await capture("landing-mobile", 390, 844);
  await visit("/sign-in");
  await capture("sign-in-mobile", 390, 844);
  await evaluate(`fetch('/api/auth/demo-login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'rahul@example.com'})}).then(r=>{if(!r.ok)throw new Error('Demo login failed');return true;})`);
  await visit("/dashboard");
  await capture("dashboard-desktop", 1440, 1000);
  await capture("dashboard-mobile", 390, 844);
  await visit("/voice");
  await capture("voice-desktop", 1440, 1000);
  await capture("voice-mobile", 390, 844);
  assert.ok(await evaluate("document.body.innerText.includes('Demo · text only')"));
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Start conversation').click()");
  const promptReady = "[...document.querySelectorAll('button')].some(b=>b.textContent.includes('Which plan am I on?')&&!b.disabled)";
  await waitFor(promptReady);
  for (let index = 0; index < 4; index++) {
    await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Which plan am I on?')).click()");
    await waitFor(promptReady);
  }
  await evaluate("document.querySelector('[role=log]').scrollTop=0");
  await waitFor("document.body.innerText.includes('Jump to latest')");
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Which language do I prefer?')).click()");
  await waitFor(promptReady);
  assert.equal(await evaluate("document.querySelector('[role=log]').scrollTop"), 0, "New messages must not displace history readers");
  await evaluate("document.querySelector('aside[aria-label=\"Session context\"]').scrollIntoView()");
  await capture("voice-active-mobile", 390, 844);
  const endButtonVisible = await evaluate("(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='End');const r=b.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()");
  assert.ok(endButtonVisible, "End-call control remains in the viewport while reading the transcript");
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='End').click()");
  await waitFor("document.body.innerText.includes('Conversation ended.')");
  await visit("/conversations");
  await capture("archive-mobile", 390, 844);
  await capture("archive-narrow", 320, 740);
  await evaluate(`fetch('/api/auth/logout',{method:'POST'}).then(r=>r.ok)`);
  } else {
    await visit("/sign-in");
  }
  await evaluate(`fetch('/api/auth/demo-login', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'ananya@acme.example'})}).then(r=>{if(!r.ok)throw new Error('Admin login failed');return true;})`);
  await visit("/customers");
  await capture("customers-desktop", 1440, 1000);
  await capture("customers-mobile", 390, 844);
  const customerPath = await evaluate("document.querySelector('a[href^=\"/customers/\"]').getAttribute('href')");
  await visit(customerPath);
  await capture("editor-desktop", 1440, 1000);
  await capture("editor-mobile", 390, 844);
  await capture("editor-narrow", 320, 740);
  await evaluate(`(()=>{
    const input=document.querySelector('input[type=text]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Unsaved review draft');
    input.dispatchEvent(new Event('input',{bubbles:true}));
    window.__confirmCount=0;
    window.confirm=()=>{window.__confirmCount++;return false;};
  })()`);
  await waitFor("document.querySelector('input[type=text]').value==='Unsaved review draft'");
  await new Promise(resolve=>setTimeout(resolve,200));
  await evaluate("[...document.querySelectorAll('a')].find(a=>a.textContent.includes('All customers')).click()");
  assert.equal(await evaluate("location.pathname"), customerPath, "Cancelled navigation stays on the editor");
  assert.equal(await evaluate("window.__confirmCount"), 1, "A single shared draft warning is shown");
  await evaluate("window.confirm=()=>true; [...document.querySelectorAll('a')].find(a=>a.textContent.includes('All customers')).click()");
  await waitFor(`location.pathname==='/customers' && document.querySelector('a[href=${JSON.stringify(customerPath)}]')`);
  await evaluate(`document.querySelector('a[href=${JSON.stringify(customerPath)}]').click()`);
  await waitFor(`location.pathname===${JSON.stringify(customerPath)} && document.querySelector('input[type=text]')`);
  assert.equal(await evaluate("document.querySelector('input[type=text]').value"), "Unsaved review draft", "Draft survives client-side navigation");
  // Reset the unsaved profile; this smoke test must never submit customer changes.
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Reset').click()");
  console.log(process.argv.includes("--draft-only")
    ? "Passed: draft warning and restoration."
    : "Passed: transcript reading position, mobile call controls, draft warning and restoration.");
  console.log(`Screenshots saved to ${output}`);
} finally {
  socket?.close();
  chrome.kill();
}

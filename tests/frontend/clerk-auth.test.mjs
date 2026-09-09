import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test, { beforeEach } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const stateKey = "__svaraClerkAuthTestState";
const clerkMock = `
  export async function auth() {
    const state = globalThis.${stateKey};
    state.authCalls += 1;
    return { getToken: async () => state.token };
  }
`;

const moduleUrls = new Map([
  ["@clerk/nextjs/server", `data:text/javascript,${encodeURIComponent(clerkMock)}`],
  ["@/lib/api-validation", pathToFileURL(resolve(root, "src/lib/api-validation.ts")).href],
  ["server-only", "data:text/javascript,export{}"],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    const url = moduleUrls.get(specifier);
    return url ? { shortCircuit: true, url } : nextResolve(specifier, context);
  },
});

const { getSessionToken } = await import(
  pathToFileURL(resolve(root, "src/lib/server-api.ts")).href
);

beforeEach(() => {
  globalThis[stateKey] = { authCalls: 0, token: "clerk-session-token" };
});

test("server API forwards the current Clerk session token", async () => {
  assert.equal(await getSessionToken(), "clerk-session-token");
  assert.equal(globalThis[stateKey].authCalls, 1);
});

test("server API returns null when Clerk has no active session", async () => {
  globalThis[stateKey].token = null;
  assert.equal(await getSessionToken(), null);
});

test("Clerk is wired at the application boundary with the required proxy matcher", () => {
  const layout = readFileSync(resolve(root, "src/app/layout.tsx"), "utf8");
  const productLayout = readFileSync(resolve(root, "src/app/(product)/layout.tsx"), "utf8");
  const proxy = readFileSync(resolve(root, "src/proxy.ts"), "utf8");
  const apiMatcher = proxy.indexOf('"/(api|trpc)(.*)"');
  const clerkMatcher = proxy.indexOf('"/__clerk/:path*"');

  assert.match(layout, /<body>\s*<ClerkProvider>\{children\}<\/ClerkProvider>\s*<\/body>/);
  assert.ok(apiMatcher >= 0);
  assert.ok(clerkMatcher > apiMatcher);
  assert.equal(proxy.match(/\/__clerk\/:path\*/g)?.length, 1);
  assert.equal(existsSync(resolve(root, "proxy.ts")), false);
  assert.match(productLayout, /const \{ userId \} = await auth\(\)/);
});

test("legacy Supabase and custom-cookie auth entry points are removed", () => {
  const packageJson = JSON.parse(readFileSync(resolve(root, "package.json"), "utf8"));

  assert.equal(packageJson.dependencies["@supabase/ssr"], undefined);
  assert.equal(packageJson.dependencies["@supabase/supabase-js"], undefined);
  assert.equal(existsSync(resolve(root, "src/lib/supabase/config.ts")), false);
  assert.equal(existsSync(resolve(root, "src/lib/supabase/server.ts")), false);
  assert.equal(existsSync(resolve(root, "src/lib/supabase/proxy.ts")), false);
  assert.equal(existsSync(resolve(root, "src/app/api/auth/sign-in/route.ts")), false);
  assert.equal(existsSync(resolve(root, "src/app/api/auth/logout/route.ts")), false);
  assert.equal(existsSync(resolve(root, "src/app/api/auth/demo-login/route.ts")), false);
});

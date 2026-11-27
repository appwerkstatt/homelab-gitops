// Prüft stacks/13-n8n/hooks/keycloak-sso.js gegen ein laufendes n8n (gestartet von check-n8n-sso-hook.sh).
// Simuliert, was Traefik liefert: X-Auth-Request-Email (oauth2-proxy) + X-N8n-Sso-Secret (Middleware n8n-sso-secret).
import { chromium } from 'playwright-core';

const base = process.env.N8N_BASE_URL;
const secret = process.env.SSO_SECRET;
const email = 'owner@example.org';
let failed = 0;
const check = (name, ok, extra = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${extra ? ` (${extra})` : ''}`);
  if (!ok) failed++;
};

const setup = await fetch(`${base}/rest/owner/setup`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ email, firstName: 'CI', lastName: 'Owner', password: 'Ci-Passwort-123' }),
});
check('Owner anlegen', setup.ok, `HTTP ${setup.status}`);

const login = (headers) => fetch(`${base}/rest/login`, { headers });
const sso = { 'X-Auth-Request-Email': email, 'X-N8n-Sso-Secret': secret, 'browser-id': 'ci-browser' };

for (const [name, h] of [
  ['ohne Header', {}],
  ['nur E-Mail, kein Secret', { 'X-Auth-Request-Email': email }],
  ['falsches Secret', { 'X-Auth-Request-Email': email, 'X-N8n-Sso-Secret': 'falsch' }],
  ['unbekannte E-Mail', { ...sso, 'X-Auth-Request-Email': 'fremd@example.org' }],
]) {
  const r = await login(h);
  check(`abgelehnt: ${name}`, r.status === 401 && !r.headers.get('set-cookie'), `HTTP ${r.status}`);
}

const r = await login({ ...sso, 'X-Auth-Request-Email': 'Owner@Example.org' });
const body = await r.json().catch(() => ({}));
const cookie = (r.headers.get('set-cookie') || '').match(/n8n-auth=([^;]+)/)?.[1];
check('angemeldet mit Secret + E-Mail', r.status === 200 && body?.data?.email === email && !!cookie, `HTTP ${r.status}`);

const api = (bid) => fetch(`${base}/rest/workflows`, { headers: { cookie: `n8n-auth=${cookie}`, 'browser-id': bid } });
check('Cookie gilt für die REST-API', (await api('ci-browser')).status === 200);
check('Cookie ist an browser-id gebunden', (await api('anderer-browser')).status === 401);

const wh = await fetch(`${base}/webhook/gibt-es-nicht`, { headers: sso });
check('Webhook setzt kein Cookie', !(wh.headers.get('set-cookie') || '').includes('n8n-auth'), `HTTP ${wh.status}`);

// Echter Editor im Browser: ruft der Editor weiterhin GET /rest/login, landet man ohne Login-Seite im Editor.
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const ctx = await browser.newContext({ extraHTTPHeaders: { 'X-Auth-Request-Email': email, 'X-N8n-Sso-Secret': secret } });
const page = await ctx.newPage();
const ssoLogin = page.waitForResponse((res) => new URL(res.url()).pathname.endsWith('/rest/login') && res.request().method() === 'GET', { timeout: 30000 }).catch(() => null);
await page.goto(`${base}/signin`);
const res1 = await ssoLogin;
await page.waitForURL((u) => u.pathname.includes('/home/'), { timeout: 30000 }).catch(() => {});
check('Editor im Browser ohne n8n-Login', res1?.status() === 200 && new URL(page.url()).pathname.includes('/home/'), `GET /rest/login ${res1?.status()}, ${page.url()}`);
const anon = await (await browser.newContext()).newPage();
const anonLogin = anon.waitForResponse((res) => new URL(res.url()).pathname.endsWith('/rest/login') && res.request().method() === 'GET', { timeout: 30000 }).catch(() => null);
await anon.goto(`${base}/home/workflows`);
const res2 = await anonLogin;
await anon.waitForURL((u) => u.pathname.includes('/signin'), { timeout: 30000 }).catch(() => {});
check('ohne Header bleibt die Login-Seite', res2?.status() === 401 && new URL(anon.url()).pathname.includes('/signin'), `GET /rest/login ${res2?.status()}, ${anon.url()}`);
await browser.close();

if (failed) {
  console.log(`::error file=stacks/13-n8n/hooks/keycloak-sso.js::${failed} Prüfung(en) des Keycloak-Hooks fehlgeschlagen`);
  process.exit(1);
}
console.log('Keycloak-Hook: alle Prüfungen ok');

'use strict';
// keycloak-sso.js — n8n External Hook (EXTERNAL_HOOK_FILES): Keycloak-Login ohne zweiten n8n-Login.
//
// Ablauf: Traefik lässt den Editor nur nach Keycloak-Login durch (sso-devs@docker, oauth2-proxy) und gibt
// die bestätigte E-Mail als X-Auth-Request-Email weiter. Zusätzlich setzt Traefik NUR auf dem Editor-Router
// den geheimen Header X-N8n-Sso-Secret (Middleware n8n-sso-secret in compose.yaml). Lädt der Editor
// GET /rest/login (fragt "wer bin ich?"), stellt dieser Hook für den SCHON VORHANDENEN n8n-Benutzer mit
// dieser E-Mail das normale n8n-Session-Cookie aus. Konten legt er nicht an, Rollen ändert er nicht.
//
// Lizenz: nutzt nur die offene External-Hook-Schnittstelle und AuthService.issueJWT/issueCookie der
// Community-Edition (dieselben Aufrufe wie der Passwort-Login). Kein .ee-Code, keine Lizenzprüfung umgangen.
//
// Sicherheit:
// - n8n kennt nur den SHA-256 des Secrets (N8N_SSO_SECRET_SHA256). Wer Umgebung oder Dateien des
//   n8n-Containers liest (z.B. ein Workflow), kann sich damit nicht anmelden; Anfragen direkt an
//   n8n:5678 (Workflows über localhost, andere Container in edge-n8n) haben das Secret nicht.
// - Traefik überschreibt X-Auth-Request-* mit der Antwort von oauth2-proxy (authResponseHeaders) und
//   entfernt beide Header auf den Webhook-Routern (Middleware n8n-strip-sso).
// - oauth2-proxy akzeptiert nur in Keycloak bestätigte E-Mails (Default, kein --insecure-oidc-allow-unverified-email).
// - Das Cookie ist an die browser-id des Editors gebunden (wie beim Passwort-Login).
//
// Fail-open: Passt etwas an n8ns Interna nicht mehr (Update), loggt der Hook "keycloak-sso: DEAKTIVIERT"
// (Loki-Alert N8nSsoHookDisabled) und n8n läuft mit dem eigenen Passwort-Login weiter.
// CI: scripts/check-n8n-sso-hook.sh startet die n8n-Version aus compose.yaml mit diesem Hook und prüft den Ablauf.
const crypto = require('node:crypto');
const { createRequire } = require('node:module');

const PREFIX = 'keycloak-sso:';
const SECRET_HEADER = 'x-n8n-sso-secret';
const EMAIL_HEADER = 'x-auth-request-email';

function disabled(reason) {
  console.error(`${PREFIX} DEAKTIVIERT: ${reason} (n8n-eigener Login bleibt aktiv)`);
}

module.exports = {
  n8n: {
    ready: [
      async function keycloakSsoSetup(server) {
        try {
          const hashHex = (process.env.N8N_SSO_SECRET_SHA256 || '').trim().toLowerCase();
          if (!/^[0-9a-f]{64}$/.test(hashHex)) return disabled('N8N_SSO_SECRET_SHA256 fehlt oder ist kein SHA-256');
          const expected = Buffer.from(hashHex, 'hex');

          // Module aus n8ns eigenem node_modules laden (require.main = .../node_modules/n8n/bin/n8n)
          const n8nRequire = createRequire(require.main.filename);
          const { Container } = n8nRequire('@n8n/di');
          const { AuthService } = n8nRequire('../dist/auth/auth.service.js');
          const { AUTH_COOKIE_NAME } = n8nRequire('../dist/constants.js');
          const userRepo = this.dbCollections?.User;
          const auth = Container.get(AuthService);
          if (typeof auth.issueJWT !== 'function' || typeof auth.issueCookie !== 'function')
            return disabled('AuthService.issueJWT/issueCookie fehlen');
          if (!AUTH_COOKIE_NAME || typeof userRepo?.findOne !== 'function')
            return disabled('AUTH_COOKIE_NAME oder Benutzer-Repository fehlen');

          // Express 5: Middleware direkt hinter cookie-parser einhängen, also vor alle Routen
          const stack = server.app?.router?.stack;
          const cpIndex = Array.isArray(stack) ? stack.findIndex((l) => l.name === 'cookieParser') : -1;
          if (cpIndex < 0) return disabled('Express-Router oder cookieParser nicht gefunden');

          const isTrusted = (req) => {
            const s = req.headers[SECRET_HEADER];
            if (typeof s !== 'string' || s.length === 0) return false;
            return crypto.timingSafeEqual(crypto.createHash('sha256').update(s).digest(), expected);
          };

          const keycloakSso = async function keycloakSso(req, res, next) {
            if (req.method !== 'GET' || req.path !== '/rest/login') return next();
            try {
              if (!isTrusted(req)) return next();
              const raw = req.headers[EMAIL_HEADER];
              const email = typeof raw === 'string' ? raw.trim().toLowerCase() : '';
              if (!email.includes('@')) return next();
              const user = await userRepo.findOne({ where: { email }, relations: ['role'] });
              if (!user || user.disabled) {
                console.warn(`${PREFIX} kein aktives n8n-Konto für ${email}, n8n-Login nötig`);
                return next();
              }
              const browserId = typeof req.headers['browser-id'] === 'string' ? req.headers['browser-id'] : undefined;
              // usedMfa=true: Keycloak erzwingt Passkey/2FA bei jedem Login (docs/dienste/keycloak.md)
              const token = auth.issueJWT(user, true, browserId);
              auth.issueCookie(res, user, true, browserId);
              req.cookies[AUTH_COOKIE_NAME] = token; // diese Anfrage gilt schon als angemeldet
            } catch (e) {
              console.error(`${PREFIX} Fehler bei ${req.headers[EMAIL_HEADER]}: ${e.message}`);
            }
            return next();
          };

          server.app.use(keycloakSso);
          const layer = stack.pop();
          if (layer?.handle !== keycloakSso) {
            if (layer) stack.push(layer);
            return disabled('Middleware liess sich nicht einhängen');
          }
          stack.splice(cpIndex + 1, 0, layer);
          console.log(`${PREFIX} aktiv`);
        } catch (e) {
          disabled(e.message);
        }
      },
    ],
  },
};

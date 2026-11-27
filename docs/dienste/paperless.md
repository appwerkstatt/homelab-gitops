# 11-paperless

| | |
|---|---|
| **Zweck** | Dokumentenarchiv mit OCR (Paperless-ngx) und KI-Suche/Tagging (paperless-ai) |
| **Adresse** | `https://docs.lab.appsfab.org`, `https://docs-ai.lab.appsfab.org` |
| **Login** | Paperless: Keycloak (OIDC, Client `paperless`) auf das eigene Paperless-Konto, siehe [Keycloak-Login](#keycloak-login); paperless-ai: `sso-admin@docker` (nur `lab-admins`) |
| **Daten** | `data/paperless/{media,consume,export}`, `fast/appdata/paperless/{db,redis,data}`, `fast/appdata/paperless-ai` |
| **Backup** | Dokumente Tier 1 (alle 12 h) + offsite; DB Tier 2 + `pg_dump` offsite |
| **Abhängig von** | Ollama auf dem Mac Studio (`192.168.80.30:11434`) für paperless-ai |
| **Quelle** | [`stacks/11-paperless/compose.yaml`](https://github.com/appwerkstatt/homelab-gitops/blob/main/stacks/11-paperless/compose.yaml) |

## Bausteine

- **paperless** + **paperless-db** (Postgres 17) + **paperless-redis** (Celery-Broker, zustandslos).
- **paperless-ai**: Modell `qwen2.5:14b`, Embeddings `nomic-embed-text` über Ollama; die RAG-Embeddings
  rechnet v4 lokal, daher `mem_limit: 2g`.
- Neue Dokumente kommen über den SMB-Eingang `data/paperless/consume`.

## Keycloak-Login

Paperless meldet über **allauth** (`openid_connect`, Provider-ID `keycloak`) bei Keycloak an. Das ist eine
freie Funktion von Paperless-ngx, nichts wird gepatcht.

- **Keine neuen Konten:** `PAPERLESS_SOCIALACCOUNT_ALLOW_SIGNUPS=false`. Wer in Keycloak ist, aber kein
  verknüpftes Paperless-Konto hat, sieht „Sign Up Closed“. Konten, Rechte und die Gruppe `haushalt` bleiben
  in Paperless; Keycloak-Gruppen werden **nicht** übernommen.
- **Verknüpfen (einmal pro Person):** mit dem Paperless-Passwort anmelden → Profil (oben rechts) →
  Abschnitt *Connected social accounts* → **Keycloak** → Passkey. Ab dann reicht der Button „Keycloak“ auf der
  Login-Seite. Prüfen als Superuser: Django-Admin → *Social accounts*.
- **API und Apps:** paperless-ai, Homepage und Handy-Apps nutzen API-Tokens und merken nichts.

### Rollout

1. `openssl rand -base64 32 | tr -d '/+='` → 1Password `homelab-paperless`, Feld `oidc-client-secret`.
2. `scripts/render-env.sh keycloak` und `scripts/render-env.sh paperless` in die Arcane-Envs einfügen
   (`PAPERLESS_OIDC_CLIENT_SECRET` in **beiden**), erst Keycloak deployen, dann Paperless.
3. Alle vier verknüpfen ihr Konto (siehe oben). Die Konten in Paperless brauchen dafür nichts Besonderes.
4. **Schritt 2**, wenn alle verknüpft haben: im `compose.yaml` `PAPERLESS_DISABLE_REGULAR_LOGIN` und
   `PAPERLESS_REDIRECT_LOGIN_TO_SSO` auf `"true"`. Dann springt die Login-Seite direkt zu Keycloak und das
   Passwortformular ist aus.

**Achtung:** Auch mit `DISABLE_REGULAR_LOGIN` nimmt die **API** weiter Benutzername + Passwort an (Basic Auth,
`/api/token/`, getestet mit 3.4.1). Nach Schritt 2 die Paperless-Passwörter darum auf lange Zufallswerte
setzen (Christian: in 1Password `homelab-paperless` als Notzugang ablegen), sonst umgeht ein erratenes
Passwort den Passkey.

**Notausgang (Keycloak weg):** Schritt 2 zurückdrehen, dann geht das Passwort wieder; oder im Container
`python3 manage.py changepassword <user>`.

## Stolperfallen

- **paperless-ai meldet HTTP 400 („does not accept the host name paperless“):** Seit Paperless 3.5 sind
  nur der Host aus `PAPERLESS_URL` und `localhost` erlaubt. `PAPERLESS_ALLOWED_HOSTS: paperless` im
  `compose.yaml` muss bleiben, weil paperless-ai intern `http://paperless:8000` aufruft.
- **„Sign Up Closed“ nach dem Keycloak-Login:** Das Konto ist noch nicht verknüpft. Mit Passwort anmelden und
  im Profil verbinden (vor Schritt 2), sonst als Superuser im Django-Admin einen *Social account* anlegen
  (Provider `keycloak`, UID = Keycloak-User-ID).
- **Paperless-eigene 2FA (TOTP):** Wer sie eingerichtet hat, wird nach dem Keycloak-Login noch einmal gefragt
  (Keycloak schickt kein `amr`-Claim). Sie kann aus, Keycloak verlangt schon den Passkey.
- **Abmelden** beendet nur die Paperless-Sitzung; die Keycloak-Sitzung bleibt, der nächste Klick auf
  „Keycloak“ meldet sofort wieder an.

- Ist der Mac Studio aus, läuft paperless-ai ins Leere; Alarm `LlmHostDown`. Paperless selbst läuft weiter.
- Postgres nicht auf 18 heben (Vorfall 2026-06-05); Renovate macht das bewusst nicht.

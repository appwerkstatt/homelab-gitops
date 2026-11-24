# Rechtekonzept

Wer darf was? Alle Rechte hängen an **zwei Keycloak-Gruppen** im Realm `AppsFab`. Selbstregistrierung ist aus,
neue Benutzer legt nur ein Admin in der Keycloak-Admin-Konsole an (`auth.lab`, nur LAN).

| Gruppe | Für wen | Bedeutung |
|---|---|---|
| `lab-users` | **jeden** Menschen mit Zugang, auch Admins | darf sich bei den Nutzer-Diensten anmelden |
| `lab-admins` | nur Admins | zusätzlich Admin-Rechte und Admin-Werkzeuge |

Ein Admin ist also in **beiden** Gruppen. Ein Benutzer ohne Gruppe kommt nirgends rein.
Keinem Benutzer im Realm `AppsFab` Rollen des Clients `realm-management` geben: Keycloak verwalten nur
Konten im Realm `master`.

## Zwei Türsteher in Traefik

Für Dienste ohne eigenes OIDC gibt es zwei Middlewares, beide über oauth2-proxy ([03-oauth2-proxy](../dienste/oauth2-proxy.md)):

| Middleware | Lässt durch | Für |
|---|---|---|
| `sso@docker` | `lab-users` | Nutzer-Apps |
| `sso-admin@docker` | nur `lab-admins` | Admin-Werkzeuge |

`sso-admin` hängt an die Adresse von oauth2-proxy `?allowed_groups=lab-admins`. Ohne Sitzung geht es wie bei
`sso` zu Keycloak, eingeloggt ohne `lab-admins` antwortet oauth2-proxy mit **403**. Beide nutzen dieselbe
Sitzung und denselben Keycloak-Client, ein neuer Host braucht also nur die Callback-URL beim Client `oauth2-proxy`.

**Faustregel für neue Dienste:** Kann der Dienst Daten aller Benutzer sehen, Konfiguration ändern oder hat er
Zugriff auf Infrastruktur, kommt er hinter `sso-admin@docker`.

## Dienste im Überblick

| Dienst | Schranke | Admin | Normaler Benutzer (`lab-users`) |
|---|---|---|---|
| Keycloak | eigene Admin-Konsole, nur LAN | Konten im Realm `master` | eigene Account-Seite (Passkeys, Passwort) |
| Grafana | OIDC, nur `lab-users`/`lab-admins` | `lab-admins` → Admin | Viewer: sieht alle Dashboards, auch Logs |
| Forgejo | OIDC, nur `lab-users` (`--required-claim-*`) | `lab-admins` → Site-Admin | Konto nur, wenn ein Admin es anlegt (Registrierung aus); sieht öffentliche Repos |
| Zot | OIDC | `lab-admins`: alles | nur lesen |
| Netboot | OIDC | `lab-admins` dürfen „armen“ | darf ansehen |
| Homepage, Handbuch | `sso` | – | sieht alles (Widget-Tokens bleiben auf dem Server) |
| Plane | `sso`, God Mode `sso-admin` | Plane-Instanz-Admin | eigenes Plane-Konto, Rolle im Workspace |
| Paperless | eigenes Login (kein SSO) | Superuser | eigenes Konto, sieht nur eigene und freigegebene Dokumente (siehe unten) |
| paperless-ai | `sso-admin` + eigenes Login | Admin | kein Zugang: nutzt ein API-Token, das alle Dokumente sieht |
| n8n | `sso-admin` + eigenes Login | Owner | **vorerst kein Zugang** (siehe unten) |
| Traefik-Dashboard | `sso-admin` | lesend | kein Zugang |
| Arcane, TrueNAS | eigenes Login, nur VLAN 10 ([NAS-Firewall](../nas-firewall/README.md)) | lokale Konten | kein Konto |

## Neuen Benutzer anlegen

1. Keycloak-Admin-Konsole (`https://auth.lab.appsfab.org/admin`, Realm `master`) → Realm `AppsFab` → *Users* →
   *Add user*, E-Mail setzen, Gruppe **nur `lab-users`**. Unter *Role mapping* keine weiteren Rollen.
2. Beim ersten Login registriert die Person einen Passkey (Pflicht, siehe [Login & SSO](sso.md)).
3. Apps mit eigenen Konten nur bei Bedarf:
    - **Forgejo:** Die Registrierung ist aus, das Konto legt ein Admin an. Nur in die Repos und Teams
      aufnehmen, die gebraucht werden.
    - **Plane:** im Workspace als *Member* einladen, nicht als Admin.
    - **Paperless:** Benutzer **ohne** Superuser und **ohne** Staff anlegen, Rechte über eine Gruppe.

## Stolperfallen

- **Paperless: Dokumente ohne Besitzer sieht jeder Benutzer.** Vor dem ersten weiteren Konto alle Dokumente
  ohne Besitzer einem Besitzer zuweisen (Dokumente → Filter „Besitzer: keiner“ → Massenbearbeitung → Rechte)
  und einen Workflow „Dokument hinzugefügt → Besitzer zuweisen“ anlegen, damit neue Uploads nicht offen sind.
- **n8n:** Jeder n8n-Member erreicht im Netz `edge-n8n` VictoriaMetrics, Loki und Alertmanager ohne Login
  (SECURITY.md, Punkt N), sähe also alle Logs und könnte Alarme stummschalten. Deshalb steht der Editor hinter
  `sso-admin`. Erst wenn das abgesichert ist, zurück auf `sso` und Benutzer als *Member* einladen.
- **Plane:** In God Mode → *Authentication* „Allow anyone to sign up“ aus lassen, sonst legt sich jeder
  `lab-users`-Benutzer selbst ein Konto an.
- **Grafana:** Viewer sehen das Dashboard *Homelab Logs* und damit alle Container-Logs. Soll das nicht so
  sein, den Ordner per Berechtigung auf Admins beschränken.
- **Forgejo:** Die Gruppenpflicht steht in der Datenbank, nicht in der Env. Nachziehen mit
  `forgejo admin auth update-oauth --id 6 --required-claim-name groups --required-claim-value lab-users`
  (Befehl im `compose.yaml`), danach den Container neu starten. Prüfen mit `forgejo admin auth list`.
- **Arcane und TrueNAS** sind aus dem ganzen VLAN 10 erreichbar. Hängen Geräte anderer Personen in diesem
  VLAN, `MGMT_CIDRS` in der NAS-Firewall auf die Admin-Geräte eingrenzen und in TrueNAS 2FA einschalten.

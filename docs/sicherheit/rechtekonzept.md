# Rechtekonzept

Wer darf was? Das Homelab hat **vier Benutzer**: Christian (Admin), seine Frau, Sohn und Tochter, alle
volljährig. Alle Rechte hängen an Keycloak-Gruppen im Realm `AppsFab`. Selbstregistrierung ist aus, neue
Benutzer legt nur ein Admin in der Keycloak-Admin-Konsole an (`auth.lab`, nur LAN). Alles ist **nur im LAN**
erreichbar, außer `git`, `auth` und `hooks.appsfab.org`.

## Gruppen

| Gruppe | Mitglieder | Bedeutung |
|---|---|---|
| `lab-users` | alle vier | darf sich bei den Nutzer-Diensten anmelden (`sso@docker`) |
| `family` | alle vier | Familie; Merkmal für künftige Familien-Apps (z. B. Fotos) |
| `devs` | Christian, Sohn | Forgejo, n8n, Registry lesen (`sso-devs@docker`) |
| `lab-admins` | nur Christian | Admin-Rechte und Admin-Werkzeuge (`sso-admin@docker`) |

Ein Admin ist in **allen** Gruppen. Ein Benutzer ohne Gruppe kommt nirgends rein.
Keinem Benutzer im Realm `AppsFab` Rollen des Clients `realm-management` geben: Keycloak verwalten nur
Konten im Realm `master`.

## Drei Türsteher in Traefik

Für Dienste ohne eigenes OIDC gibt es drei Middlewares, alle über oauth2-proxy ([03-oauth2-proxy](../dienste/oauth2-proxy.md)):

| Middleware | Lässt durch | Für |
|---|---|---|
| `sso@docker` | `lab-users` | Familien-Apps |
| `sso-devs@docker` | `devs` | Entwickler-Werkzeuge |
| `sso-admin@docker` | `lab-admins` | Admin-Werkzeuge |

`sso-devs` und `sso-admin` hängen an die Adresse von oauth2-proxy `?allowed_groups=<gruppe>`. Ohne Sitzung
geht es wie bei `sso` zu Keycloak, eingeloggt ohne die Gruppe antwortet oauth2-proxy mit **403**. Alle nutzen
dieselbe Sitzung und denselben Keycloak-Client, ein neuer Host braucht also nur die Callback-URL beim Client
`oauth2-proxy`.

**Faustregel für neue Dienste:** Kann der Dienst Daten aller Benutzer sehen, Konfiguration ändern oder hat er
Zugriff auf Infrastruktur, kommt er hinter `sso-admin@docker`.

## Dienste im Überblick

| Dienst | Schranke | Christian | Frau, Tochter | Sohn |
|---|---|---|---|---|
| Startseite `home.lab` | `sso` | ✓ | ✓ | ✓ |
| Admin-Startseite `admin.lab` | `sso-admin` | ✓ | – | – |
| Plane | `sso` + Plane-Konto, God Mode `sso-admin` | Instanz-Admin | Member im Familien-Workspace | Member |
| Paperless | eigenes Login | Superuser | eigene + gemeinsame Dokumente | eigene + gemeinsame Dokumente |
| Keycloak-Konto | – | ✓ | ✓ (Passkeys, Passwort) | ✓ |
| Forgejo | OIDC, nur `devs` | Site-Admin (`lab-admins`) | – | eigenes Konto, nur freigegebene Repos |
| n8n | `sso-devs` + n8n-Konto | Owner | – | Member |
| Zot | OIDC | alles (`lab-admins`) | – | lesen (`devs`) |
| Grafana | OIDC, nur `lab-admins` | Admin | – | – |
| Netboot | OIDC | „armen“ (`lab-admins`) | nur ansehen | nur ansehen |
| Handbuch | `sso` | ✓ | lesen | lesen |
| paperless-ai, Traefik-Dashboard | `sso-admin` | ✓ | – | – |
| Arcane, TrueNAS | eigenes Login, nur VLAN 10 | lokale Konten | – | – |

## n8n für Entwickler

n8n-Member dürfen Workflows bauen und HTTP-Anfragen ins Netz `edge-n8n` schicken. Damit das nicht zu allen Logs
führt, hängen VictoriaMetrics, Loki und Alertmanager **nicht** in `edge-n8n`:

- n8n liest Metriken und Logs nur über **vmauth** (`http://vmauth:8427`): nur Lese-Pfade, nur mit Bearer-Token.
  Das Token liegt im n8n-Credential *Observability lesen* des Owners und wird **nicht** geteilt.
- Alertmanager schickt den Alert-Erklärer-Webhook über Traefik (`https://n8n.lab.appsfab.org/webhook/…`).

Was ein n8n-Member trotzdem erreicht: Traefik (alle `*.lab`-Hosts, also wieder mit Login), den blackbox-Exporter
(nur „erreichbar ja/nein“), die LLMs auf dem Mac Studio und das Internet. Credentials des Owners sieht er nicht.

## Neuen Benutzer anlegen

1. Keycloak-Admin-Konsole (`https://auth.lab.appsfab.org/admin`, Realm `master`) → Realm `AppsFab` → *Users* →
   *Add user*, E-Mail setzen, Gruppen `lab-users` und `family`, für Entwickler zusätzlich `devs`. Unter
   *Role mapping* keine weiteren Rollen.
2. Beim ersten Login registriert die Person einen Passkey (Pflicht, siehe [Login & SSO](sso.md)).
3. Apps mit eigenen Konten:
    - **Plane:** in den Familien-Workspace als *Member* einladen.
    - **Paperless:** Benutzer **ohne** Superuser und **ohne** Staff anlegen, Rechte über die Paperless-Gruppe
      `haushalt` (siehe unten).
    - **Forgejo** (nur `devs`): Die Registrierung ist aus, das Konto legt ein Admin an. Nur in die Repos und
      Teams aufnehmen, die gebraucht werden.
    - **n8n** (nur `devs`): als *Member* einladen, nicht als Admin.

## Paperless: private und gemeinsame Dokumente

Paperless hat eigene Konten und Rechte pro Dokument:

- Jeder ist **Besitzer** seiner eigenen Dokumente; die sieht sonst niemand (außer dem Superuser).
- Gemeinsame Dokumente (Verträge, Versicherungen, Steuern) bekommen zusätzlich Rechte für die Paperless-Gruppe
  **`haushalt`** (Ansehen + Bearbeiten).
- Ein Workflow „Dokument hinzugefügt → Besitzer = hochladende Person“ sorgt dafür, dass neue Uploads nicht offen sind.

**Wichtig:** Dokumente **ohne** Besitzer sieht jeder Benutzer. Vor dem ersten weiteren Konto alle Dokumente
ohne Besitzer einem Besitzer zuweisen (Dokumente → Filter „Besitzer: keiner“ → Massenbearbeitung → Rechte).

## Stolperfallen

- **Plane:** In God Mode → *Authentication* „Allow anyone to sign up“ aus lassen, sonst legt sich jeder
  `lab-users`-Benutzer selbst ein Konto an.
- **Forgejo:** Die Gruppenpflicht steht in der Datenbank, nicht in der Env. Nachziehen mit
  `forgejo admin auth update-oauth --id 6 --required-claim-name groups --required-claim-value devs`
  (Befehl im `compose.yaml`), danach den Container neu starten. Prüfen mit `forgejo admin auth list`.
- **Zot** liest seine Config beim Start: nach Änderungen an `zot.json` den Container neu starten, falls die
  Rechte nicht sofort greifen.
- **Arcane und TrueNAS** sind aus dem ganzen VLAN 10 erreichbar. Hängen Geräte der Familie in diesem VLAN,
  `MGMT_CIDRS` in der NAS-Firewall auf die Admin-Geräte eingrenzen und in TrueNAS 2FA einschalten.
- **Von unterwegs** geht vorerst nichts (Entscheidung 2026-11-24). Später: VPN (WireGuard in UniFi) oder
  öffentliche Hosts über den Tunnel.

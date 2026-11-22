# Konventionen

Regeln, die für alle Stacks gelten. Weicht ein Stack ab, steht der Grund als Kommentar im `compose.yaml`.

## Aufbau eines Stacks

- Ordner `stacks/<nn>-<name>/` mit `compose.yaml`, optional `config/` und `README.md`.
- Die Nummer ordnet grob nach Abhängigkeit: `0x` Fundament (Proxy, Identität), `1x` Anwendungen,
  `2x` Infrastruktur-Dienste, `3x` Provisioning, `40` Dashboard.
- **Image-Versionen sind gepinnt**, nie `latest`. Versionen stehen nur im `compose.yaml`, nicht in der Doku;
  Renovate hält sie aktuell.
- **Jeder Service hat ein `mem_limit`.** Das NAS hat 24 GB; kein einzelner Container darf es lahmlegen.
- Datenbanken haben kein Port-Mapping und hängen nur in einem stack-internen Netz.
- Persistente Daten per Bind-Mount auf `/mnt/fast/appdata/<dienst>` oder `/mnt/data/<…>`.

## Arcane setzt den Projektnamen

Arcane startet jeden Stack als `docker compose -p <slug> …`. Der Slug kommt aus dem **Anzeigenamen der
Gitsync-App**, nicht aus `name:` im `compose.yaml`. Beispiele: „Garage S3“ → `garages3`,
„Registry ZOT“ → `registryzot`. Container heißen deshalb z. B. `garages3-garage-1`, obwohl
`name: garage` nahelegt. Das ist **erwartet**.

!!! danger "Nie `docker compose up` ohne `-p <slug>`"
    Sonst legt Compose ein zweites Projekt auf **denselben** Bind-Mounts an. Bei Garage (LMDB) oder Zot
    schreiben dann zwei Prozesse in dasselbe Datenverzeichnis, das kann die Daten zerstören.
    Deployt wird immer über Arcane.

Neue Gitsync-Apps deshalb genau so benennen wie das `name:`-Feld (z. B. `plane`, `registry-cache`).
Einige Skripte verlassen sich auf den Containernamen, z. B. das Offsite-Backup auf `plane-plane-db-1`.

## Konfigurationsänderungen, die Arcane nicht sieht

Arcane deployt neu, wenn sich `compose.yaml` ändert. Eine reine Änderung an einer gemounteten Datei löst
oft keinen Neustart aus, und manche Dienste lesen ihre Datei nur beim Start. Darum gibt es
**Revisionszähler**, die man im selben Commit hochzählt:

| Datei geändert | Zähler im `compose.yaml` | Warum |
|---|---|---|
| `stacks/02-keycloak/realm/*.json` | `KCC_REALM_REV` | keycloak-config-cli läuft nur neu, wenn sich sein Container ändert |
| `stacks/12-cloudflared/config.yml` | `CF_INGRESS_REV` | cloudflared liest die Ingress-Regeln nur beim Start |

Für Grafana-Provisioning (Datasources, Dashboard-Provider) gibt es keinen Zähler: Grafana nach der Änderung
von Hand neu starten.

## Routing und Login

- Jeder geroutete Dienst setzt `traefik.docker.network=edge-<stack>`.
- **SSO**: Kann die App OIDC, spricht sie selbst mit Keycloak (Grafana, Forgejo, Zot, Netboot). Sonst
  kommt die Traefik-Middleware `sso@docker` (oauth2-proxy) davor.
- Für jeden neuen Host hinter `sso@docker` muss dessen Callback `https://<host>/oauth2/callback` beim
  Keycloak-Client `oauth2-proxy` eingetragen werden (Keycloak kennt keine Host-Wildcards). Details:
  [Login & SSO](../sicherheit/sso.md).
- Öffentlich wird nur, was im Tunnel (`stacks/12-cloudflared/config.yml`) **und** mit einem Router für einen
  `*.appsfab.org`-Host steht.

## Secrets

Kein Secret im Repo. Jede Variable, die ein `compose.yaml` liest, steht in `.env.example`, Secrets als
`op://AppsFab/<item>/<feld>`. Die CI prüft das. Ablauf: [Secrets](../sicherheit/secrets.md).

## Sprache und Stil

- Doku und Kommentare auf Deutsch, Commit-Titel nach Conventional Commits (`feat(plane): …`, `fix(backup): …`).
- Zeitangaben in Europe/Berlin.
- Keine Jobs auf dem NAS um **04:00** planen: Dann startet ein TrueNAS-Cron `middlewared` neu und bricht
  laufende Jobs ab.

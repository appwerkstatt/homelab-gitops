# Fehlersuche

Bekannte Probleme aus dem Betrieb, jeweils mit Ursache und Lösung.

## Erst mal schauen

1. Telegram: welcher Alarm, was sagt der Alert-Erklärer?
2. Grafana *Homelab · Übersicht* → *Dienste & Erreichbarkeit* → *Logs* (Filter auf den Container).
3. Arcane: läuft der Stack, gab es einen Deploy-Fehler?
4. Zuletzt gemergte PRs (Renovate!) im Tagesbericht oder auf GitHub.

## Doppelte Container

**Symptom**: Login klappt nur manchmal, `authentication_expired` oder fehlendes CSRF-Cookie, 403 auf `home.lab`.
**Ursache**: Ein verwaister Container aus einem alten Arcane-Projekt hat dieselben Traefik-Labels. Traefik verteilt
abwechselnd, Docker-DNS löst auf den falschen auf.
**Lösung**: `docker ps --format '{{.Names}} {{.Label "com.docker.compose.project"}}'` nach Dubletten durchsehen,
den alten Container in Arcane entfernen. Nach jedem Umzug eines Stacks prüfen.

## Hairpin: NAS erreicht `*.lab` nicht

**Symptom**: `curl https://registry.lab.appsfab.org` vom NAS hängt.
**Ursache**: macvlan, der Host kann `.48` nicht erreichen ([Netzwerk](../architektur/netzwerk.md#traefik-auf-eigener-ip-macvlan)).
**Lösung**: vom NAS `127.0.0.1:5000` (Zot) bzw. `:5001` (Cache) nehmen oder aus einem Container testen.

## Änderung an einer Config-Datei wirkt nicht

**Ursache**: Arcane deployt nur bei Änderungen am `compose.yaml`; manche Dienste lesen Dateien nur beim Start.
**Lösung**: `KCC_REALM_REV` (Keycloak-Realm) bzw. `CF_INGRESS_REV` (Tunnel) hochzählen; Grafana-Provisioning:
Grafana neu starten. Grafana 13 zeigt neue Ordner in der Ordneransicht manchmal verspätet, Seite neu laden.

## Tunnel-Host liefert 404

**Ursache**: cloudflared läuft noch mit alten Ingress-Regeln, oder der Ziel-Router fehlt.
**Lösung**: `CF_INGRESS_REV` geprüft? Traefik-Router für genau diesen Host und Pfad vorhanden?

## OIDC-Login eines Dienstes bricht nach Deploy

**Ursache**: `*_OIDC_CLIENT_SECRET` fehlt in der Env von `keycloak`, kcc hat das Secret leer gesetzt.
**Lösung**: Variable in Arcane → keycloak setzen, Keycloak neu deployen. Bei `invalid_scope`: `groups` aus den
angefragten Scopes entfernen. Bei „Invalid redirect_uri“: Callback im Realm-Client ergänzen.

## Nächtlicher Job bricht ab

**Ursache**: Um 04:00 startet TrueNAS `middlewared` neu. Die Replikation hing so ab 2026-11-08 fest.
**Lösung**: nichts um 04:00 planen. Replikation läuft deshalb um 04:30.

## SSH vom Mac zum NAS hängt

**Symptom**: Timeout bei SSH, Ping und HTTPS gehen. Am 2026-11-22 kam das von selbst wieder.
**Vermutung**: UniFi-IPS (Threat Management) hat den Mac kurz geblockt.
**Prüfen**: auf dem NAS `sudo tcpdump -ni enp3s0 port 22`; in UniFi *Insights → Threat Management* nach der
Mac-IP suchen. Für SSH immer `192.168.80.50` nehmen ([Netzwerk](../architektur/netzwerk.md)).

## Container wird OOM-gekillt

**Ursache**: `mem_limit` zu knapp (Beispiele: paperless-ai beim Embedding, Grafana, Homepage).
**Lösung**: im Dashboard *Container & Stacks* RAM gegen Limit ansehen, Limit im `compose.yaml` begründet anheben.

## Postgres startet nach Update nicht

**Ursache**: Major-Sprung (z. B. 17 → 18) braucht `pg_upgrade`, ein Tag-Tausch reicht nicht.
**Lösung**: Image auf die alte Major zurück (Revert-PR). Renovate macht Postgres-Majors bewusst nicht.

## Mac Studio nach Stromausfall nicht erreichbar

**Ursache**: FileVault wartet auf das Passwort; LaunchDaemon und LM Studio starten erst danach.
**Lösung**: am Mac anmelden. Details im [Mac-Studio-Runbook](../mac-studio-llm.md).

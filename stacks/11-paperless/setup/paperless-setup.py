#!/usr/bin/env python3
"""Richtet die Paperless-Automatisierung über die REST-API ein (idempotent, nur Python-Standardbibliothek).

Legt an, was fehlt, und lässt Bestehendes in Ruhe (gleicher Name = vorhanden; --update überschreibt
Workflows und Ansichten mit dem Stand aus diesem Skript):

  * Custom Fields  Betrag, Fällig am, Bezahlt, Vertragsende, Kündigen bis, Steuerjahr
  * Tags           Rechnung, Vertrag, Versicherung, Steuer, Haushalt, E-Mail (mit Auto-Zuordnung)
  * Workflows      Besitzer für den Consume-Ordner (pro Unterordner), Teilen mit `haushalt`,
                   Felder für Rechnungen/Verträge/Steuer, Leserecht für den n8n-Benutzer
  * Ansichten      Rechnungen offen, Verträge mit Frist, Steuer <Jahr>, Steuer ohne Jahr
  * --n8n-user     Paperless-Benutzer `n8n` (nur Lesen) + API-Token für die n8n-Workflows
  * --backfill     wendet Felder und Rechte auch auf schon vorhandene Dokumente an
  * --mail         iCloud-/IMAP-Postfach + Mail-Regel (Zugangsdaten aus der Umgebung, siehe unten)

Aufruf (vom Mac, Token = API-Token eines Superusers, Paperless → Profil → API-Token):
  export PAPERLESS_TOKEN=$(op read op://AppsFab/homelab-paperless/setup-api-token)
  python3 stacks/11-paperless/setup/paperless-setup.py --dry-run       # zeigt nur, was passieren würde
  python3 stacks/11-paperless/setup/paperless-setup.py --n8n-user --backfill

Mail (--mail), alle aus der Umgebung:
  PAPERLESS_MAIL_USER      Login (bei iCloud die @icloud.com- bzw. Apple-ID-Adresse, nicht der Alias)
  PAPERLESS_MAIL_PASSWORD  App-spezifisches Passwort (appleid.apple.com), aus 1Password
  PAPERLESS_MAIL_HOST      Standard imap.mail.me.com      PAPERLESS_MAIL_PORT    Standard 993 (SSL)
  PAPERLESS_MAIL_FOLDER    Standard Paperless             PAPERLESS_MAIL_DONE    Standard Paperless-Erledigt

Handbuch: docs/dienste/paperless.md → Automatisierung. Getestet in CI mit scripts/check-paperless-setup.sh.
"""
import argparse
import datetime
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

# --- Personen und Gruppen (müssen in Paperless schon existieren, siehe docs/sicherheit/rechtekonzept.md) ---
DEFAULT_OWNER = "christian"          # Besitzer für Scans im Consume-Ordner ohne Personen-Unterordner
CONSUME_OWNERS = {"christian": "christian", "gisa": "gisa"}   # Unterordner -> Benutzer
SHARE_GROUP = "haushalt"             # gemeinsame Dokumente (nur Christian + Gisa)
N8N_USER = "n8n"
N8N_PERMISSIONS = ["view_document", "view_tag", "view_customfield", "view_correspondent", "view_documenttype"]

# --- Custom Fields (Name, Typ, extra_data) ---
FIELDS = [
    ("Betrag", "monetary", {"default_currency": "EUR"}),
    ("Fällig am", "date", None),
    ("Bezahlt", "boolean", None),
    ("Vertragsende", "date", None),
    ("Kündigen bis", "date", None),
    ("Steuerjahr", "integer", None),
]

# --- Tags: Name, Farbe, Wörter für die Auto-Zuordnung "irgendein Wort" (None = keine Auto-Zuordnung) ---
TAGS = [
    ("Rechnung", "#e8590c", "Rechnung Rechnungsnummer Rechnungsbetrag Zahlungsziel Abschlagsrechnung"),
    ("Vertrag", "#1971c2", "Vertragsnummer Vertragslaufzeit Mindestlaufzeit Vertragsbestätigung Auftragsbestätigung"),
    ("Versicherung", "#0c8599", "Versicherungsschein Versicherungsnummer Versicherungsbeitrag Beitragsrechnung Police"),
    ("Steuer", "#2f9e44", "Lohnsteuerbescheinigung Steuerbescheid Finanzamt Zuwendungsbestätigung Spendenquittung "
                          "Steuernummer Steuer-ID Identifikationsnummer"),
    ("Haushalt", "#9c36b5", "Stadtwerke Stromrechnung Gasrechnung Abschlag Rundfunkbeitrag Grundsteuer "
                            "Nebenkostenabrechnung Müllgebühren Wasserversorgung"),
    ("E-Mail", "#868e96", None),
]
SHARED_TAGS = ["Haushalt", "Vertrag", "Versicherung", "Steuer"]   # -> Gruppe haushalt (Rechtekonzept)

# Paperless-Konstanten (documents/models.py, src-ui filter-rule-type.ts)
MATCH_NONE, MATCH_ANY = 0, 1
TRIGGER_CONSUMPTION, TRIGGER_ADDED, TRIGGER_UPDATED = 1, 2, 3
SOURCE_CONSUME_FOLDER, SOURCE_API, SOURCE_MAIL = 1, 2, 3
ACTION_ASSIGNMENT = 1
RULE_HAS_TAGS_ALL, RULE_HAS_TAGS_ANY, RULE_CUSTOM_FIELD_QUERY = 6, 22, 42


class Api:
    def __init__(self, url, token, dry_run):
        self.base = url.rstrip("/") + "/api"
        self.token = token
        self.dry_run = dry_run
        self.fake_id = 0
        self.version = None

    def probe_version(self):
        """Neueste API-Version des Servers (Header X-Api-Version), damit alle Felder der aktuellen API gelten."""
        req = urllib.request.Request(self.base + "/", headers={"Authorization": "Token " + self.token})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self.version = r.headers.get("X-Api-Version")
        except urllib.error.HTTPError as e:
            sys.exit(f"FEHLER: {self.base}/ antwortet mit HTTP {e.code} (Token falsch?)")
        return self.version

    def request(self, method, path, data=None, token=None, form=None):
        url = path if path.startswith("http") else self.base + path
        headers = {"Accept": "application/json" + (f"; version={self.version}" if self.version else "")}
        body = None
        if token or self.token:
            headers["Authorization"] = "Token " + (token or self.token)
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers.pop("Authorization", None)
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            sys.exit(f"FEHLER {method} {url}: HTTP {e.code}\n{detail}")

    def write(self, method, path, data, what):
        if self.dry_run:
            print(f"  [dry-run] {method} {path}: {what}")
            self.fake_id -= 1
            return {"id": self.fake_id, **(data if isinstance(data, dict) else {})}
        return self.request(method, path, data)

    def all(self, path, **params):
        params.setdefault("page_size", 1000)
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        out = []
        while url:
            page = self.request("GET", url)
            out += page["results"]
            url = page.get("next")
        return out


def by_name(objs, key="name"):
    return {o[key].casefold(): o for o in objs}


def ensure_fields(api):
    print("Custom Fields")
    existing = by_name(api.all("/custom_fields/"))
    ids = {}
    for name, dtype, extra in FIELDS:
        cur = existing.get(name.casefold())
        if cur:
            if cur["data_type"] != dtype:
                print(f"  ! {name}: existiert als {cur['data_type']}, erwartet {dtype} (bitte von Hand prüfen)")
            else:
                print(f"  = {name}")
            ids[name] = cur["id"]
            continue
        data = {"name": name, "data_type": dtype}
        if extra:
            data["extra_data"] = extra
        ids[name] = api.write("POST", "/custom_fields/", data, f"Feld {name} ({dtype})")["id"]
        print(f"  + {name} ({dtype})")
    return ids


def ensure_tags(api):
    print("Tags")
    existing = by_name(api.all("/tags/"))
    ids = {}
    for name, color, words in TAGS:
        cur = existing.get(name.casefold())
        if cur:
            ids[name] = cur["id"]
            print(f"  = {name} (Zuordnung bleibt, wie sie ist)")
            continue
        # owner None: ohne Besitzer sehen alle Konten (Gisa, n8n) den Tag; Dokumente bleiben trotzdem privat
        data = {"name": name, "color": color, "is_insensitive": True, "owner": None,
                "matching_algorithm": MATCH_ANY if words else MATCH_NONE, "match": words or ""}
        ids[name] = api.write("POST", "/tags/", data, f"Tag {name}")["id"]
        print(f"  + {name}")
    return ids


def lookup_principals(api):
    users = by_name(api.all("/users/"), "username")
    groups = by_name(api.all("/groups/"))
    missing = [u for u in {DEFAULT_OWNER, *CONSUME_OWNERS.values()} if u.casefold() not in users]
    if SHARE_GROUP.casefold() not in groups:
        missing.append(f"Gruppe {SHARE_GROUP}")
    if missing:
        sys.exit("FEHLER: in Paperless fehlt: " + ", ".join(missing) + " (Rechtekonzept zuerst umsetzen)")
    return ({k: v["id"] for k, v in users.items()}, groups[SHARE_GROUP.casefold()]["id"])


def ensure_n8n_user(api, create):
    users = by_name(api.all("/users/"), "username")
    cur = users.get(N8N_USER)
    if cur:
        print(f"Benutzer {N8N_USER}: vorhanden (Token steht in 1Password homelab-paperless/n8n-api-token)")
        return cur["id"]
    if not create:
        print(f"Benutzer {N8N_USER}: fehlt, Leserecht für n8n wird ausgelassen (mit --n8n-user anlegen)")
        return None
    password = secrets.token_urlsafe(32)
    data = {"username": N8N_USER, "password": password, "is_active": True, "is_staff": False,
            "is_superuser": False, "first_name": "n8n", "user_permissions": N8N_PERMISSIONS}
    user = api.write("POST", "/users/", dict(data, password="***") if api.dry_run else data,
                     f"Benutzer {N8N_USER} mit {', '.join(N8N_PERMISSIONS)}")
    print(f"Benutzer {N8N_USER}: angelegt")
    if not api.dry_run:
        token = api.request("POST", "/token/", form={"username": N8N_USER, "password": password})["token"]
        print("\n  API-Token für n8n (nur jetzt sichtbar) -> 1Password homelab-paperless/n8n-api-token,")
        print("  in n8n als Header-Auth-Credential 'Paperless lesen': Authorization = Token <Token>")
        print(f"  n8n-Token: {token}\n")
    return user["id"]


def workflows_spec(f, t, users, share_gid, n8n_uid):
    viewers = [n8n_uid] if n8n_uid else []

    def consume(name, order, path, owner, extra=None):
        action = {"type": ACTION_ASSIGNMENT, "assign_owner": users[owner]}
        action.update(extra or {})
        return {"name": name, "order": order, "enabled": True,
                "triggers": [{"type": TRIGGER_CONSUMPTION, "sources": [SOURCE_CONSUME_FOLDER],
                              "filter_path": path, "matching_algorithm": MATCH_NONE}],
                "actions": [action]}

    def on_tags(name, order, tags, action):
        trig = [{"type": typ, "sources": [SOURCE_CONSUME_FOLDER, SOURCE_API, SOURCE_MAIL],
                 "filter_has_tags": [t[x] for x in tags], "matching_algorithm": MATCH_NONE}
                for typ in (TRIGGER_ADDED, TRIGGER_UPDATED)]
        return {"name": name, "order": order, "enabled": True, "triggers": trig,
                "actions": [dict(type=ACTION_ASSIGNMENT, **action)]}

    # Reihenfolge zählt: spätere Zuweisungen überschreiben frühere (Besitzer aus dem Unterordner gewinnt).
    specs = [consume("Consume-Ordner: Besitzer " + DEFAULT_OWNER, 10, "*/consume/*", DEFAULT_OWNER)]
    for i, (folder, user) in enumerate(sorted(CONSUME_OWNERS.items())):
        if user != DEFAULT_OWNER:
            specs.append(consume(f"Consume-Ordner {folder}/: Besitzer {user}", 11 + i, f"*/consume/{folder}/*", user))
    specs.append(consume("Consume-Ordner haushalt/: Haushalt", 15, "*/consume/haushalt/*", DEFAULT_OWNER,
                         {"assign_tags": [t["Haushalt"]]}))
    specs += [
        on_tags(f"Gemeinsam: mit {SHARE_GROUP} teilen", 20, SHARED_TAGS,
                {"assign_view_groups": [share_gid], "assign_change_groups": [share_gid]}),
        on_tags("Rechnung: Felder Betrag/Fällig/Bezahlt", 30, ["Rechnung"],
                {"assign_custom_fields": [f["Betrag"], f["Fällig am"], f["Bezahlt"]], "assign_view_users": viewers}),
        on_tags("Vertrag: Felder Vertragsende/Kündigen bis", 31, ["Vertrag", "Versicherung"],
                {"assign_custom_fields": [f["Vertragsende"], f["Kündigen bis"]], "assign_view_users": viewers}),
        on_tags("Steuer: Feld Steuerjahr", 32, ["Steuer"],
                {"assign_custom_fields": [f["Steuerjahr"]], "assign_view_users": viewers}),
    ]
    return specs


def ensure_named(api, path, label, specs, update):
    print(label)
    existing = by_name(api.all(path))
    for spec in specs:
        cur = existing.get(spec["name"].casefold())
        if cur and not update:
            print(f"  = {spec['name']}")
        elif cur:
            api.write("PUT", f"{path}{cur['id']}/", spec, f"{spec['name']} überschreiben")
            print(f"  ~ {spec['name']} (überschrieben)")
        else:
            api.write("POST", path, spec, spec["name"])
            print(f"  + {spec['name']}")


def q(expr):
    return json.dumps(expr, ensure_ascii=False)


def views_spec(f, t, share_gid, years):
    share = {"view": {"users": [], "groups": [share_gid]}, "change": {"users": [], "groups": []}}
    cf = lambda name: f"custom_field_{f[name]}"  # noqa: E731

    def view(name, rules, sort, cols, dashboard=True, reverse=False):
        return {"name": name, "show_on_dashboard": dashboard, "show_in_sidebar": True,
                "sort_field": sort, "sort_reverse": reverse, "display_mode": "table",
                "display_fields": ["title", "correspondent", *cols],
                "filter_rules": rules, "set_permissions": share}

    specs = [
        view("Rechnungen offen",
             [{"rule_type": RULE_HAS_TAGS_ALL, "value": str(t["Rechnung"])},
              {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q(["NOT", [f["Bezahlt"], "exact", True]])}],
             cf("Fällig am"), [cf("Fällig am"), cf("Betrag"), cf("Bezahlt")]),
        view("Verträge mit Frist",
             [{"rule_type": RULE_HAS_TAGS_ANY, "value": str(t["Vertrag"])},
              {"rule_type": RULE_HAS_TAGS_ANY, "value": str(t["Versicherung"])},
              {"rule_type": RULE_CUSTOM_FIELD_QUERY,
               "value": q(["OR", [[f["Kündigen bis"], "isnull", False], [f["Vertragsende"], "isnull", False]]])}],
             cf("Kündigen bis"), [cf("Kündigen bis"), cf("Vertragsende")]),
        view("Steuer: ohne Steuerjahr",
             [{"rule_type": RULE_HAS_TAGS_ALL, "value": str(t["Steuer"])},
              {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q(["NOT", [f["Steuerjahr"], "isnull", False]])}],
             "created", ["created"], dashboard=False, reverse=True),
    ]
    for year in years:
        specs.append(view(f"Steuer {year}",
                          [{"rule_type": RULE_HAS_TAGS_ALL, "value": str(t["Steuer"])},
                           {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q([f["Steuerjahr"], "exact", year])}],
                          "created", ["created", cf("Betrag")], dashboard=False))
    return specs


def backfill(api, f, t, share_gid, n8n_uid):
    """Wie die Workflows, nur für schon vorhandene Dokumente. Werte vorhandener Felder bleiben unangetastet."""
    print("Backfill vorhandener Dokumente")

    def docs(tags, field_missing=None):
        params = {"tags__id__in": ",".join(str(t[x]) for x in tags), "fields": "id"}
        if field_missing:
            params["custom_field_query"] = q(["NOT", [f[field_missing], "exists", True]])
        return [d["id"] for d in api.all("/documents/", **params)]

    def bulk(ids, method, parameters, what):
        if not ids:
            print(f"  = {what}: nichts zu tun")
            return
        api.write("POST", "/documents/bulk_edit/", {"documents": ids, "method": method, "parameters": parameters},
                  f"{what} ({len(ids)} Dokumente)")
        print(f"  + {what}: {len(ids)} Dokumente")

    def perms(view_users=(), view_groups=(), change_groups=()):
        return {"set_permissions": {"view": {"users": list(view_users), "groups": list(view_groups)},
                                    "change": {"users": [], "groups": list(change_groups)}},
                "merge": True}   # merge: Besitzer und bestehende Rechte bleiben

    bulk(docs(SHARED_TAGS), "set_permissions", perms(view_groups=[share_gid], change_groups=[share_gid]),
         f"mit {SHARE_GROUP} teilen")
    groups = [(["Rechnung"], ["Betrag", "Fällig am", "Bezahlt"]),
              (["Vertrag", "Versicherung"], ["Vertragsende", "Kündigen bis"]),
              (["Steuer"], ["Steuerjahr"])]
    for tags, fields in groups:
        if n8n_uid:
            bulk(docs(tags), "set_permissions", perms(view_users=[n8n_uid]), f"{'/'.join(tags)}: n8n darf lesen")
        for name in fields:
            # nur Dokumente OHNE das Feld: bulk_edit würde vorhandene Werte sonst auf leer setzen
            bulk(docs(tags, field_missing=name), "modify_custom_fields",
                 {"add_custom_fields": [f[name]], "remove_custom_fields": []}, f"{'/'.join(tags)}: Feld {name}")


def ensure_mail(api, t, users):
    env = os.environ
    user, password = env.get("PAPERLESS_MAIL_USER"), env.get("PAPERLESS_MAIL_PASSWORD")
    if not user or not password:
        sys.exit("FEHLER: --mail braucht PAPERLESS_MAIL_USER und PAPERLESS_MAIL_PASSWORD")
    host = env.get("PAPERLESS_MAIL_HOST", "imap.mail.me.com")
    port = int(env.get("PAPERLESS_MAIL_PORT", "993"))
    folder = env.get("PAPERLESS_MAIL_FOLDER", "Paperless")
    done = env.get("PAPERLESS_MAIL_DONE", "Paperless-Erledigt")
    owner = env.get("PAPERLESS_MAIL_OWNER", DEFAULT_OWNER)
    print(f"Mail: {user} @ {host}:{port}, Ordner {folder} -> {done}")
    account = {"name": f"Mail {user}", "imap_server": host, "imap_port": port, "imap_security": 2,  # 2 = SSL
               "username": user, "password": password, "character_set": "UTF-8", "account_type": 1}
    if not env.get("PAPERLESS_MAIL_SKIP_TEST") and not api.dry_run:
        res = api.request("POST", "/mail_accounts/test/", account)
        if not (res or {}).get("success"):
            sys.exit(f"FEHLER: IMAP-Login fehlgeschlagen: {res}")
        print("  IMAP-Login ok")
    existing = by_name(api.all("/mail_accounts/"))
    cur = existing.get(account["name"].casefold())
    if cur:
        api.write("PATCH", f"/mail_accounts/{cur['id']}/", {"password": password, "imap_server": host,
                                                           "imap_port": port}, "Zugang aktualisieren")
        acc_id = cur["id"]
        print(f"  = Konto {account['name']} (Zugang aktualisiert)")
    else:
        acc_id = api.write("POST", "/mail_accounts/", account, f"Konto {account['name']}")["id"]
        print(f"  + Konto {account['name']}")
    rule = {"name": f"Belege aus {folder}", "account": acc_id, "enabled": True, "folder": folder, "order": 10,
            "maximum_age": 90, "action": 2, "action_parameter": done,   # 2 = in Ordner verschieben
            "attachment_type": 1, "consumption_scope": 1,                # nur Anhänge (Belege, keine Signaturbilder)
            "assign_title_from": 2, "assign_correspondent_from": 1,     # Titel = Dateiname, Korrespondent: Auto-Zuordnung
            "assign_tags": [t["E-Mail"]], "assign_owner_from_rule": True, "owner": users[owner.casefold()]}
    rules = by_name(api.all("/mail_rules/"))
    if rule["name"].casefold() in rules:
        print(f"  = Regel {rule['name']}")
    else:
        api.write("POST", "/mail_rules/", rule, f"Regel {rule['name']}")
        print(f"  + Regel {rule['name']}")


def main():
    year = datetime.date.today().year
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=os.environ.get("PAPERLESS_URL", "https://docs.lab.appsfab.org"))
    p.add_argument("--dry-run", action="store_true", help="nichts ändern, nur anzeigen")
    p.add_argument("--update", action="store_true", help="vorhandene Workflows/Ansichten überschreiben")
    p.add_argument("--n8n-user", action="store_true", help="Benutzer n8n (nur Lesen) anlegen und Token ausgeben")
    p.add_argument("--backfill", action="store_true", help="Felder/Rechte auf vorhandene Dokumente anwenden")
    p.add_argument("--mail", action="store_true", help="Mail-Konto + Regel anlegen (PAPERLESS_MAIL_*)")
    p.add_argument("--tax-years", type=int, nargs="*", default=[year - 1, year], help="Steuer-Ansichten")
    a = p.parse_args()
    token = os.environ.get("PAPERLESS_TOKEN")
    if not token:
        sys.exit("FEHLER: PAPERLESS_TOKEN fehlt (API-Token eines Superusers)")

    api = Api(a.url, token, a.dry_run)
    version = api.probe_version()
    me = api.request("GET", "/profile/")
    print(f"Paperless {a.url} (API v{version}) als {me.get('username', '?')}{' (dry-run)' if a.dry_run else ''}\n")
    users, share_gid = lookup_principals(api)
    f = ensure_fields(api)
    t = ensure_tags(api)
    n8n_uid = ensure_n8n_user(api, a.n8n_user)
    ensure_named(api, "/workflows/", "Workflows", workflows_spec(f, t, users, share_gid, n8n_uid), a.update)
    ensure_named(api, "/saved_views/", "Gespeicherte Ansichten", views_spec(f, t, share_gid, a.tax_years), a.update)
    if a.backfill:
        backfill(api, f, t, share_gid, n8n_uid)
    if a.mail:
        ensure_mail(api, t, users)
    print("\nFertig.")


if __name__ == "__main__":
    main()

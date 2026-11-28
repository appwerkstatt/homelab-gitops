#!/usr/bin/env python3
"""Richtet die Paperless-Automatisierung über die REST-API ein (idempotent, nur Python-Standardbibliothek).

Legt an, was fehlt, und lässt Bestehendes in Ruhe (gleicher Name = vorhanden; --update überschreibt
Workflows und Ansichten mit dem Stand aus diesem Skript):

  * Custom Fields  Betrag, Fällig am, Bezahlt, Vertragsende, Kündigen bis, Steuerjahr, Garantie bis
  * Tags           Rechnung, Vertrag, Versicherung, Steuer, Haushalt, E-Mail (mit Auto-Zuordnung) und die
                   Lebensbereiche (Haus, Finanzen, Vorsorge, Gesundheit, Auto, Arbeit, Kinder, Technik, Freizeit)
  * --tags-aufraeumen  alle anderen Tags zusammenlegen (TAG_MERGE) oder löschen, erst mit --dry-run ansehen
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
import time
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
    ("Garantie bis", "date", None),   # an Rechnungen für Geräte; n8n erinnert 30 Tage vorher
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
    # Lebensbereiche (höchstens einer pro Dokument, ohne Stichwörter): setzt paperless-ai
    # ("Restrict to existing tags") oder man selbst. Was/von wem steht in Dokumenttyp/Korrespondent, nicht im Tag.
    ("Haus", "#ae3ec9", None),          # Grundsteuer, Energie, Internet, Handwerker
    ("Finanzen", "#5c940d", None),      # Bank, Kreditkarte, Depot, Solarpark, Schufa
    ("Vorsorge", "#1098ad", None),      # Rente, Altersvorsorge
    ("Gesundheit", "#e03131", None),
    ("Auto", "#495057", None),
    ("Arbeit", "#f08c00", None),
    ("Kinder", "#f783ac", None),        # Schule, Kita, alles zu Tom und der Tochter
    ("Technik", "#3b5bdb", None),       # Homelab, Apple, UniFi, Garmin
    ("Freizeit", "#74b816", None),      # Fahrrad, Sport, Mitgliedschaften
]
# --tags-aufraeumen: TAGS oben + KEEP_TAGS sind die Positivliste. Jeder andere Tag geht im Ziel aus TAG_MERGE auf
# (Dokumente bekommen das Ziel, der alte Tag wird gelöscht) oder wird gelöscht, wenn er nirgends steht.
# Gleich geschriebene Tags in anderer Groß-/Kleinschreibung werden zusammengelegt bzw. umbenannt.
KEEP_TAGS = ["ai-verarbeitet"]   # merkt sich paperless-ai für bearbeitete Dokumente; Posteingangs-Tags bleiben auch
TAG_MERGE = {
    "Rechnung": ["invoice", "invoices", "bill", "bills", "kaufbeleg", "Abrechnung", "Abrechnungen"],
    "Vertrag": ["contract", "contracts", "agreement", "Verträge", "Versorgungsverträge", "Abonnement", "Subscription"],
    "Versicherung": ["insurance", "Krankenversicherung", "Krankheitskostenversicherung", "Pflegeversicherung",
                     "Pflegepflichtversicherung", "Kfz-Versicherung"],
    "Steuer": ["tax", "taxes", "steuerrelevant", "Steuerbescheinigung", "Steuererklärung 2025", "Finanzamt",
               "Kapitalerträge", "Aktienveräußerungen", "Kinderfreibeträge", "Vorsorgeaufwendungen",
               "Abziehbare Spenden"],
    "Haushalt": ["household"],
    "Haus": ["Wohnung", "Grundsteuer", "Grundsteuerwertbescheid", "Gas", "Internet", "Telekommunikation", "möbel",
             "garten", "werkzeug"],
    "Finanzen": ["Bank", "Finance", "Banking", "Banken", "Bankgeschäft", "Finanzdienstleistung", "Kreditkarte",
                 "Kreditkarten", "Schufa", "Kreditwürdigkeit", "Solarpark"],
    "Vorsorge": ["Rentenberechnung", "Rentenversicherung", "Altersvorsorgebeiträge"],
    "Gesundheit": ["Pflege", "healthcare", "Augenglas", "Sportbrille"],
    "Auto": ["BMW", "Fahrzeug", "connecteddrive", "Radwechsel", "Kfz"],
    "Arbeit": ["löhne", "geschäftlich"],
    "Kinder": ["Schule", "Kita"],
    "Technik": ["computer", "Computerhardware", "elektronik", "Apple", "ASUS", "Garmin", "UniFi", "networking",
                "Network", "Netzwerkgeräte", "L3-Routing", "Kabelleitungen", "accessories", "3d-druck", "audio"],
    "Freizeit": ["fahrrad", "bicycle", "Bike Discount", "sport", "Sports Equipment", "training", "Haus Kiekeberg",
                 "travel"],
}
SHARED_TAGS = ["Haushalt", "Vertrag", "Versicherung", "Steuer", "Haus", "Kinder"]   # -> Gruppe haushalt (Rechtekonzept)
# Englische Tags, die KI-Vorschläge (paperless-ai, Paperless-KI) anlegen. Gibt es sie, zählen sie in Workflows,
# Ansichten und Backfill wie der deutsche Tag (Entscheidung Christian 2026-11-28: beide Sprachen akzeptieren).
TAG_ALIASES = {
    "Rechnung": ["invoice", "invoices", "bill", "bills"],
    "Vertrag": ["contract", "contracts", "agreement"],
    "Versicherung": ["insurance"],
    "Steuer": ["tax", "taxes"],
    "Haushalt": ["household"],
}
ALIAS_IDS = {}   # deutscher Name -> IDs vorhandener Alias-Tags (füllt ensure_tags)


def tag_ids(t, names):
    """IDs der deutschen Tags plus ihrer vorhandenen englischen Aliase."""
    out = []
    for name in names:
        out += [t[name], *ALIAS_IDS.get(name, [])]
    return out

# Paperless-Konstanten (documents/models.py, src-ui filter-rule-type.ts)
MATCH_NONE, MATCH_ANY = 0, 1
TRIGGER_CONSUMPTION, TRIGGER_ADDED, TRIGGER_UPDATED = 1, 2, 3
SOURCE_CONSUME_FOLDER, SOURCE_API, SOURCE_MAIL = 1, 2, 3
ACTION_ASSIGNMENT = 1
RULE_HAS_TAGS_ANY, RULE_CUSTOM_FIELD_QUERY = 22, 42


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

    def bulk_edit(self, docs, method, parameters, what):
        """bulk_edit läuft in Paperless 3.x als Hintergrund-Task: auf das Ergebnis warten, bevor es weitergeht
        (sonst löscht das Aufräumen einen Tag, bevor seine Dokumente den neuen haben)."""
        res = self.write("POST", "/documents/bulk_edit/", {"documents": docs, "method": method,
                                                            "parameters": parameters}, what)
        task = (res or {}).get("task_id")
        if self.dry_run or not task:
            return
        for i in range(200):
            found = self.request("GET", "/tasks/?" + urllib.parse.urlencode({"task_id": task}))
            found = found.get("results", []) if isinstance(found, dict) else found
            status = str(found[0].get("status") if found else "").upper()
            if status == "SUCCESS":
                return
            if status in ("FAILURE", "REVOKED"):
                sys.exit(f"FEHLER: {what}: Paperless-Task {task} {status}: {found[0]}")
            if not found and i >= 20:
                print(f"  ! Task {task} taucht in /tasks/ nicht auf, 10 s Puffer")
                time.sleep(10)
                return
            time.sleep(1.5)
        sys.exit(f"FEHLER: {what}: Paperless-Task {task} nach 5 Minuten nicht fertig")

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
    tags = api.all("/tags/")
    existing = by_name(tags)
    exact = {x["name"]: x for x in tags}
    ids = {}
    for name, color, words in TAGS:
        cur = exact.get(name) or existing.get(name.casefold())
        if cur:
            ids[name] = cur["id"]
            print(f"  = {name} (Zuordnung bleibt, wie sie ist)")
            continue
        # owner None: ohne Besitzer sehen alle Konten (Gisa, n8n) den Tag; Dokumente bleiben trotzdem privat
        data = {"name": name, "color": color, "is_insensitive": True, "owner": None,
                "matching_algorithm": MATCH_ANY if words else MATCH_NONE, "match": words or ""}
        ids[name] = api.write("POST", "/tags/", data, f"Tag {name}")["id"]
        print(f"  + {name}")
    for name, aliases in TAG_ALIASES.items():
        found = [existing[a.casefold()] for a in aliases if a.casefold() in existing]
        ALIAS_IDS[name] = [x["id"] for x in found if x["id"] != ids[name]]
        if found:
            print(f"  = {name} gilt auch für: {', '.join(x['name'] for x in found)}")
    return ids


def tidy_tags(api, t):
    """Positivliste durchsetzen (--tags-aufraeumen), siehe TAG_MERGE. Gibt die gelöschten Tag-IDs zurück."""
    print("Tags aufräumen (Positivliste)")
    keep = {n.casefold() for n in KEEP_TAGS}
    target_of = {n.casefold(): n for n in t}                      # Schreibvarianten -> Positiv-Tag
    for target, sources in TAG_MERGE.items():
        target_of.update({s.casefold(): target for s in sources})
    deleted = set()
    for tag in sorted(api.all("/tags/"), key=lambda x: -x.get("document_count", 0)):
        name, tid, n = tag["name"], tag["id"], tag.get("document_count", 0)
        if tid in t.values():
            want = next(k for k, v in t.items() if v == tid)
            if name != want:
                api.write("PATCH", f"/tags/{tid}/", {"name": want}, f"{name} -> {want}")
                print(f"  ~ {name} heißt jetzt {want}")
            continue
        if name.casefold() in keep or tag.get("is_inbox_tag"):
            continue
        target = target_of.get(name.casefold())
        if target and n:
            docs = [d["id"] for d in api.all("/documents/", tags__id__all=tid, fields="id")]
            api.bulk_edit(docs, "add_tag", {"tag": t[target]}, f"{target} an {len(docs)} Dokumente")
        api.write("DELETE", f"/tags/{tid}/", None, f"Tag {name} löschen")
        deleted.add(tid)
        print(f"  - {name} ({n})" + (f" -> {target}" if target else " gelöscht"))
    if not deleted:
        print("  = nichts zu tun")
    return deleted


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
                 "filter_has_tags": tag_ids(t, tags), "matching_algorithm": MATCH_NONE}
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
                {"assign_custom_fields": [f["Betrag"], f["Fällig am"], f["Bezahlt"], f["Garantie bis"]],
                 "assign_view_users": viewers}),
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

    def any_tag(*names):   # "hat einen dieser Tags" (deutsch + Aliase)
        return [{"rule_type": RULE_HAS_TAGS_ANY, "value": str(i)} for i in tag_ids(t, names)]

    def view(name, rules, sort, cols, dashboard=True, reverse=False):
        return {"name": name, "show_on_dashboard": dashboard, "show_in_sidebar": True,
                "sort_field": sort, "sort_reverse": reverse, "display_mode": "table",
                "display_fields": ["title", "correspondent", *cols],
                "filter_rules": rules, "set_permissions": share}

    specs = [
        view("Rechnungen offen",
             [*any_tag("Rechnung"),
              {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q(["NOT", [f["Bezahlt"], "exact", True]])}],
             cf("Fällig am"), [cf("Fällig am"), cf("Betrag"), cf("Bezahlt")]),
        view("Verträge mit Frist",
             [*any_tag("Vertrag", "Versicherung"),
              {"rule_type": RULE_CUSTOM_FIELD_QUERY,
               "value": q(["OR", [[f["Kündigen bis"], "isnull", False], [f["Vertragsende"], "isnull", False]]])}],
             cf("Kündigen bis"), [cf("Kündigen bis"), cf("Vertragsende")]),
        view("Steuer: ohne Steuerjahr",
             [*any_tag("Steuer"),
              {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q(["NOT", [f["Steuerjahr"], "isnull", False]])}],
             "created", ["created"], dashboard=False, reverse=True),
    ]
    for year in years:
        specs.append(view(f"Steuer {year}",
                          [*any_tag("Steuer"),
                           {"rule_type": RULE_CUSTOM_FIELD_QUERY, "value": q([f["Steuerjahr"], "exact", year])}],
                          "created", ["created", cf("Betrag")], dashboard=False))
    return specs


def backfill(api, f, t, share_gid, n8n_uid):
    """Wie die Workflows, nur für schon vorhandene Dokumente. Werte vorhandener Felder bleiben unangetastet."""
    print("Backfill vorhandener Dokumente")

    cache = {}

    def docs(tags, field_missing=None, lacks=None):
        """IDs der Dokumente mit einem der Tags, denen das Feld bzw. das Recht noch fehlt (Filter in Python,
        damit ein zweiter Lauf nichts mehr anfasst)."""
        if any(i < 0 for i in tag_ids(t, tags)):
            return []   # dry-run: Tag gäbe es erst nach dem echten Lauf
        key = tuple(tags)
        if key not in cache:
            cache[key] = api.all("/documents/", tags__id__in=",".join(str(i) for i in tag_ids(t, tags)),
                                 fields="id,custom_fields,permissions", full_perms="true")
        out = []
        for d in cache[key]:
            if field_missing and f[field_missing] in {c["field"] for c in d.get("custom_fields", [])}:
                continue
            if lacks:
                kind, who, pid = lacks          # z. B. ("view", "groups", 3)
                if pid in (d.get("permissions") or {}).get(kind, {}).get(who, []):
                    continue
            out.append(d["id"])
        return out

    def bulk(ids, method, parameters, what):
        if not ids:
            print(f"  = {what}: nichts zu tun")
            return
        api.bulk_edit(ids, method, parameters, f"{what} ({len(ids)} Dokumente)")
        print(f"  + {what}: {len(ids)} Dokumente")

    def perms(view_users=(), view_groups=(), change_groups=()):
        return {"set_permissions": {"view": {"users": list(view_users), "groups": list(view_groups)},
                                    "change": {"users": [], "groups": list(change_groups)}},
                "merge": True}   # merge: Besitzer und bestehende Rechte bleiben

    bulk(docs(SHARED_TAGS, lacks=("change", "groups", share_gid)), "set_permissions", perms(view_groups=[share_gid], change_groups=[share_gid]),
         f"mit {SHARE_GROUP} teilen")
    groups = [(["Rechnung"], ["Betrag", "Fällig am", "Bezahlt", "Garantie bis"]),
              (["Vertrag", "Versicherung"], ["Vertragsende", "Kündigen bis"]),
              (["Steuer"], ["Steuerjahr"])]
    for tags, fields in groups:
        if n8n_uid:
            bulk(docs(tags, lacks=("view", "users", n8n_uid)), "set_permissions", perms(view_users=[n8n_uid]), f"{'/'.join(tags)}: n8n darf lesen")
        for name in fields:
            # nur Dokumente OHNE das Feld: bulk_edit würde vorhandene Werte sonst auf leer setzen.
            # Die Workflows mit Auslöser "aktualisiert" ergänzen Felder oft schon beim Rechte-Schritt oben.
            bulk(docs(tags, field_missing=name), "modify_custom_fields",
                 {"add_custom_fields": [f[name]], "remove_custom_fields": []}, f"{'/'.join(tags)}: Feld {name}")


def ensure_mail(api, t, users, update):
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
            # 2 = auch Inline-Anhänge: Apple Mail markiert weitergeleitete PDFs als "inline", mit 1 würden sie
            # übersprungen. Nur PDFs, damit Logos und Signaturbilder nicht als Dokument landen.
            "attachment_type": 2, "consumption_scope": 1, "filter_attachment_filename_include": "*.pdf",
            "assign_title_from": 2, "assign_correspondent_from": 1,     # Titel = Dateiname, Korrespondent: Auto-Zuordnung
            "assign_tags": [t["E-Mail"]], "assign_owner_from_rule": True, "owner": users[owner.casefold()]}
    rules = by_name(api.all("/mail_rules/"))
    cur = rules.get(rule["name"].casefold())
    if cur and update:
        api.write("PUT", f"/mail_rules/{cur['id']}/", rule, f"Regel {rule['name']} überschreiben")
        print(f"  ~ Regel {rule['name']} (überschrieben)")
    elif cur:
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
    p.add_argument("--tags-aufraeumen", action="store_true",
                   help="nur Tags der Positivliste behalten, andere zusammenlegen (TAG_MERGE) oder löschen")
    p.add_argument("--tax-years", type=int, nargs="*", default=[year - 1, year], help="Steuer-Ansichten")
    a = p.parse_args()
    token = os.environ.get("PAPERLESS_TOKEN")
    if not token:
        sys.exit("FEHLER: PAPERLESS_TOKEN fehlt (API-Token eines Superusers)")

    api = Api(a.url, token, a.dry_run)
    version = api.probe_version()
    me = api.request("GET", "/profile/")
    who = me.get("username") or me.get("email") or me.get("first_name") or "?"
    print(f"Paperless {a.url} (API v{version}) als {who}{' (dry-run)' if a.dry_run else ''}\n")
    users, share_gid = lookup_principals(api)
    f = ensure_fields(api)
    t = ensure_tags(api)
    if a.tags_aufraeumen:
        gone = tidy_tags(api, t)
        for name in ALIAS_IDS:
            ALIAS_IDS[name] = [i for i in ALIAS_IDS[name] if i not in gone]
    n8n_uid = ensure_n8n_user(api, a.n8n_user)
    ensure_named(api, "/workflows/", "Workflows", workflows_spec(f, t, users, share_gid, n8n_uid), a.update)
    ensure_named(api, "/saved_views/", "Gespeicherte Ansichten", views_spec(f, t, share_gid, a.tax_years), a.update)
    if a.backfill:
        backfill(api, f, t, share_gid, n8n_uid)
    if a.mail:
        ensure_mail(api, t, users, a.update)
    print("\nFertig.")


if __name__ == "__main__":
    main()

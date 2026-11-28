#!/usr/bin/env python3
"""Testtreiber für scripts/check-paperless-setup.sh (läuft gegen ein frisches Paperless auf PAPERLESS_URL).

Baut das Rechtekonzept nach (christian = Superuser, gisa, Gruppe haushalt), lässt paperless-setup.py
laufen und prüft Workflows, Backfill, Rechte und genau die Abfragen, die die n8n-Workflows stellen
(stacks/13-n8n/workflows/paperless-*.json, Funktion `queries` unten muss dazu passen).
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["PAPERLESS_URL"].rstrip("/")
CONSUME = pathlib.Path(os.environ["CHECK_CONSUME"])
SETUP = pathlib.Path(__file__).resolve().parent.parent / "stacks/11-paperless/setup/paperless-setup.py"
failures = []


def call(method, path, token, data=None, form=None, ok=(200, 201, 204)):
    headers = {"Accept": "application/json"}
    body = None
    if token:
        headers["Authorization"] = "Token " + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(URL + "/api" + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:1500]
        if ok == "any":
            return e.code, detail
        if e.code in ok:
            return e.code, None
        sys.exit(f"FEHLER {method} {path}: HTTP {e.code}\n{detail}")


def get(path, token, **params):
    if params:
        path += "?" + urllib.parse.urlencode(params)
    return call("GET", path, token)[1]


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def token_for(user, password):
    return call("POST", "/token/", None, form={"username": user, "password": password})[1]["token"]


def run_setup(token, *args, env_extra=None):
    env = dict(os.environ, PAPERLESS_TOKEN=token, PAPERLESS_URL=URL, **(env_extra or {}))
    r = subprocess.run([sys.executable, "-I", str(SETUP), *args], env=env, capture_output=True, text=True)
    print("\n".join("    | " + line for line in r.stdout.splitlines()))
    if r.returncode != 0:
        print(r.stderr)
        sys.exit(f"paperless-setup.py {' '.join(args)}: Exit {r.returncode}")
    return r.stdout


def wait_docs(token, count, timeout=240):
    for _ in range(timeout // 3):
        docs = get("/documents/", token, page_size=100)["results"]
        if len(docs) >= count:
            return {d["title"]: d for d in docs}
        time.sleep(3)
    print(get("/tasks/", token))
    sys.exit(f"Consume-Ordner: nach {timeout}s nur {len(docs)} von {count} Dokumenten")


def queries(F, today):
    """Gleiche Abfragen wie die Code-Nodes in paperless-fristen.json / paperless-monatsbericht.json."""
    d = lambda n: (today + datetime.timedelta(days=n)).isoformat()  # noqa: E731
    return {
        "faellig": ["AND", [[F["Fällig am"], "lte", d(7)], ["NOT", [F["Bezahlt"], "exact", True]]]],
        "fristen": ["OR", [[F["Kündigen bis"], "range", [d(0), d(30)]], [F["Vertragsende"], "range", [d(0), d(60)]]]],
        "offen": ["AND", [[F["Betrag"], "exists", True], ["NOT", [F["Bezahlt"], "exact", True]]]],
        "rechnungen": [F["Betrag"], "exists", True],
        "steuer_ohne_jahr": ["AND", [[F["Steuerjahr"], "exists", True], [F["Steuerjahr"], "isnull", True]]],
    }


def cfq(token, expr, **extra):
    res = get("/documents/", token, custom_field_query=json.dumps(expr), page_size=100,
              fields="id,title,custom_fields", **extra)
    return {d["title"] for d in res["results"]}


def main():
    pw = os.environ["CHECK_ADMIN_PASSWORD"]
    admin = token_for("admin", pw)
    today = datetime.date.today()

    print("Rechtekonzept nachbauen")
    haushalt = call("POST", "/groups/", admin, {"name": "haushalt", "permissions": []})[1]["id"]
    call("POST", "/groups/", admin, {"name": "familie", "permissions": []})
    doc_perms = ["view_document", "add_document", "change_document", "view_tag", "view_customfield",
                 "view_correspondent", "view_savedview", "add_savedview"]
    christian = call("POST", "/users/", admin, {"username": "christian", "password": pw, "is_superuser": True,
                                                 "is_staff": True, "groups": [haushalt]})[1]["id"]
    call("POST", "/users/", admin, {"username": "gisa", "password": pw, "groups": [haushalt],
                                     "user_permissions": doc_perms})
    tok = token_for("christian", pw)
    gisa_tok = token_for("gisa", pw)

    print("Bestand vor dem Setup: Tag Vertrag + Feld Vertragsende gibt es schon, ein Vertrag mit Wert")
    vertrag = call("POST", "/tags/", tok, {"name": "Vertrag", "matching_algorithm": 0})[1]["id"]
    ende = call("POST", "/custom_fields/", tok, {"name": "Vertragsende", "data_type": "date"})[1]["id"]
    invoice = call("POST", "/tags/", tok, {"name": "invoice", "matching_algorithm": 0})[1]["id"]   # wie von der KI
    (CONSUME / "alt.txt").write_text("Alter Mobilfunk-Kram ohne Schlagwort\n")
    alt = wait_docs(tok, 1)["alt"]
    call("PATCH", f"/documents/{alt['id']}/", tok, {"tags": [vertrag], "owner": christian,
                                                    "custom_fields": [{"field": ende, "value": "2027-01-31"}]})

    print("Setup --dry-run ändert nichts")
    run_setup(tok, "--dry-run", "--n8n-user", "--backfill")
    check(get("/workflows/", tok)["count"] == 0, "dry-run: keine Workflows angelegt")

    mail_env = {"PAPERLESS_MAIL_USER": "test@icloud.com", "PAPERLESS_MAIL_PASSWORD": "x",
                "PAPERLESS_MAIL_HOST": "imap.invalid", "PAPERLESS_MAIL_SKIP_TEST": "1"}
    print("Setup, erster Lauf")
    out = run_setup(tok, "--n8n-user", "--backfill", "--mail", env_extra=mail_env)
    n8n_tok = next(line.split(": ", 1)[1].strip() for line in out.splitlines() if "n8n-Token:" in line)
    print("Setup, zweiter Lauf (darf nichts anlegen)")
    out2 = run_setup(tok, "--n8n-user", "--backfill", "--mail", env_extra=mail_env)
    added = [line for line in out2.splitlines() if line.startswith("  + ")]
    check(not added, f"zweiter Lauf idempotent {added or ''}")
    run_setup(tok, "--update")   # überschreiben muss die API auch annehmen

    F = {f["name"]: f["id"] for f in get("/custom_fields/", tok, page_size=100)["results"]}
    T = {t["name"]: t["id"] for t in get("/tags/", tok, page_size=100)["results"]}
    users = {u["username"]: u["id"] for u in get("/users/", admin, page_size=100)["results"]}
    check(len(get("/workflows/", tok)["results"]) == 7, "7 Workflows")
    views = {v["name"] for v in get("/saved_views/", tok, page_size=100)["results"]}
    check({"Rechnungen offen", "Verträge mit Frist", f"Steuer {today.year}", "Steuer: ohne Steuerjahr"} <= views,
          f"Ansichten {sorted(views)}")
    rules = get("/mail_rules/", tok)["results"]
    check(len(rules) == 1 and rules[0]["action_parameter"] == "Paperless-Erledigt", "Mail-Regel")
    check(F["Vertragsende"] == ende and T["Vertrag"] == vertrag, "vorhandenes Feld/Tag wiederverwendet")

    wf = {w["name"]: w for w in get("/workflows/", tok, page_size=100)["results"]}
    rw = wf["Rechnung: Felder Betrag/Fällig/Bezahlt"]["triggers"][0]["filter_has_tags"]
    check(set(rw) == {T["Rechnung"], invoice}, f"Rechnung-Workflow gilt auch für invoice ({rw})")

    print("Backfill am alten Vertrag")
    d = get(f"/documents/{alt['id']}/", tok, full_perms="true")
    cf = {c["field"]: c["value"] for c in d["custom_fields"]}
    check(d["owner"] == christian, "Besitzer bleibt christian")
    check(cf.get(ende) == "2027-01-31", f"Vertragsende-Wert bleibt ({cf.get(ende)})")
    check(F["Kündigen bis"] in cf, "Feld Kündigen bis ergänzt")
    check(haushalt in d["permissions"]["view"]["groups"], "mit haushalt geteilt")
    check(users["n8n"] in d["permissions"]["view"]["users"], "n8n darf lesen")

    print("Consume-Ordner mit Unterordnern")
    for sub, name, text in [("gisa", "rechnung", "Rechnung Nr. 4711\nZahlungsziel 14 Tage\n"),
                            ("haushalt", "strom", "Stadtwerke Musterstadt\nAbschlag Strom Dezember\n"),
                            ("", "brief", "Hallo, nur ein Brief.\n")]:
        (CONSUME / sub).mkdir(exist_ok=True)
        if sub:
            (CONSUME / sub).chmod(0o777)   # Container-Benutzer muss die Datei nach dem Import löschen dürfen
        (CONSUME / sub / f"{name}.txt").write_text(text)
    docs = wait_docs(tok, 4)
    full = {k: get(f"/documents/{v['id']}/", tok, full_perms="true") for k, v in docs.items()}
    r, s, b = full["rechnung"], full["strom"], full["brief"]
    check(r["owner"] == users["gisa"], "gisa/ -> Besitzer gisa")
    check(T["Rechnung"] in r["tags"], "Tag Rechnung automatisch")
    check({F["Betrag"], F["Fällig am"], F["Bezahlt"]} <= {c["field"] for c in r["custom_fields"]},
          "Rechnung bekommt Betrag/Fällig am/Bezahlt")
    check(users["n8n"] in r["permissions"]["view"]["users"], "n8n darf Rechnung lesen")
    check(s["owner"] == christian and T["Haushalt"] in s["tags"], "haushalt/ -> christian + Tag Haushalt")
    check(haushalt in s["permissions"]["view"]["groups"] and haushalt in s["permissions"]["change"]["groups"],
          "haushalt/ -> mit haushalt geteilt")
    check(b["owner"] == christian and not b["permissions"]["view"]["groups"], "Wurzel -> christian, privat")

    print("KI setzt englischen Tag invoice nachträglich")
    call("PATCH", f"/documents/{b['id']}/", tok, {"tags": [invoice]})
    bi = get(f"/documents/{b['id']}/", tok, full_perms="true")
    check(F["Fällig am"] in {c["field"] for c in bi["custom_fields"]}, "invoice -> Felder (Workflow aktualisiert)")
    check(users["n8n"] in bi["permissions"]["view"]["users"], "invoice -> n8n darf lesen")
    call("PATCH", f"/documents/{b['id']}/", tok, {"tags": [], "custom_fields": [], "set_permissions": {
        "view": {"users": [], "groups": []}, "change": {"users": [], "groups": []}}})

    print("Gisa sieht Gemeinsames, n8n nur Rechnungen/Verträge")
    check(call("GET", f"/documents/{s['id']}/", gisa_tok, ok="any")[0] == 200, "gisa sieht strom")
    check(call("GET", f"/documents/{b['id']}/", gisa_tok, ok="any")[0] == 404, "gisa sieht brief nicht")
    check("Haushalt" in {t["name"] for t in get("/tags/", gisa_tok)["results"]}, "gisa sieht Tag Haushalt")
    check(call("GET", f"/documents/{b['id']}/", n8n_tok, ok="any")[0] == 404, "n8n sieht brief nicht")
    check(len(get("/custom_fields/", n8n_tok)["results"]) >= 6, "n8n sieht Custom Fields")

    print("Abfragen der n8n-Workflows (als n8n)")
    call("PATCH", f"/documents/{r['id']}/", tok, {"custom_fields": [
        {"field": F["Betrag"], "value": "EUR49.90"}, {"field": F["Fällig am"], "value": (today + datetime.timedelta(days=3)).isoformat()},
        {"field": F["Bezahlt"], "value": False}]})
    call("PATCH", f"/documents/{alt['id']}/", tok, {"custom_fields": [
        {"field": ende, "value": "2027-06-30"}, {"field": F["Kündigen bis"], "value": (today + datetime.timedelta(days=10)).isoformat()}]})
    Q = queries(F, today)
    check(cfq(n8n_tok, Q["faellig"]) == {"rechnung"}, "fällige Rechnung gefunden")
    check(cfq(n8n_tok, Q["fristen"]) == {"alt"}, "Vertragsfrist gefunden")
    check(cfq(n8n_tok, Q["offen"]) == {"rechnung"}, "offene Rechnungen")
    first = today.replace(day=1)
    nxt = (first + datetime.timedelta(days=32)).replace(day=1)
    check(cfq(n8n_tok, Q["rechnungen"], created__gte=first.isoformat(), created__lt=nxt.isoformat()) == {"rechnung"},
          "Rechnungen im Monat (created__gte/lt)")
    check(cfq(n8n_tok, Q["steuer_ohne_jahr"]) == set(), "Steuer ohne Jahr: leer")
    call("PATCH", f"/documents/{r['id']}/", tok, {"custom_fields": [
        {"field": F["Betrag"], "value": "EUR49.90"}, {"field": F["Fällig am"], "value": today.isoformat()},
        {"field": F["Bezahlt"], "value": True}]})
    check(cfq(n8n_tok, Q["faellig"]) == set(), "bezahlte Rechnung nicht mehr fällig")
    val = next(c["value"] for c in get(f"/documents/{r['id']}/", n8n_tok)["custom_fields"] if c["field"] == F["Betrag"])
    check(val == "EUR49.90", f"Betrag-Format für n8n ({val})")

    if failures:
        sys.exit(f"\n{len(failures)} Prüfung(en) fehlgeschlagen: " + "; ".join(failures))
    print("\nAlles ok.")


if __name__ == "__main__":
    main()

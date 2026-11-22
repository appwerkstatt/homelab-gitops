#!/usr/bin/env python3
"""Erzeugt die eigenen Homelab-Dashboards als Grafana-JSON (Dashboards als Code).

Quelle der Wahrheit ist DIESES Skript, nicht die JSONs: Dashboards hier ändern, dann
    python3 stacks/20-observability/build-dashboards.py
laufen lassen und Skript + JSONs zusammen committen. CI (validate.yml) prüft, dass beides
zusammenpasst. In der Grafana-UI sind die Dashboards read-only (Provider allowUiUpdates:false);
zum Ausprobieren "Save as" in einen eigenen Ordner, dann hier übernehmen.

Ausgabe: config/dashboards/homelab/*.json -> Grafana-Ordner "Homelab".
Datenquellen (config/grafana-datasources.yaml): uid victoriametrics (PromQL) und loki.
Nur Standardbibliothek, läuft mit jedem python3 >= 3.8.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent / "config" / "dashboards" / "homelab"

VM = {"type": "prometheus", "uid": "victoriametrics"}
LOKI = {"type": "loki", "uid": "loki"}

# --- wiederkehrende Selektoren -------------------------------------------------------------
PROBE_SERVICES = 'job=~"probe-http|probe-registry|probe-paperless|probe-llm"'
POOLS = 'fstype="zfs",mountpoint=~"/mnt/[^/]+"'           # Pool-Root-Datasets (wie alerts.yml)
DATASETS = 'fstype="zfs",mountpoint=~"/mnt/.+"'
DISKS = 'device=~"sd[a-z]+|nvme[0-9]+n[0-9]+"'             # ganze Platten, keine Partitionen/zvols
CPUS = 'scalar(count(node_cpu_seconds_total{mode="idle"}))'
# cadvisor: Compose-Labels per -whitelisted_container_labels (compose.yaml)
STACK = "container_label_com_docker_compose_project"
CT = f'name!="",name=~"$container",{STACK}=~"$stack"'
LOG_ERR = '(?i)(\\\\b|_)(error|err|fatal|panic|exception|crit|critical)(\\\\b|_)'
LOG_SEL = '{host="truenas", compose_project=~"$stack", container=~"$container"}'


def svc(expr):
    """Hängt ein lesbares Label `svc` an Blackbox-Serien (instance ist die Probe-URL)."""
    e = f'label_replace({expr}, "svc", "$1", "instance", "(?:https?://)?([^:/]+).*")'
    e = f'label_replace({e}, "svc", "ollama (Mac Studio)", "instance", ".*:11434/.*")'
    e = f'label_replace({e}, "svc", "lm-studio (Mac Studio)", "instance", ".*:1234/.*")'
    e = f'label_replace({e}, "svc", "zot", "instance", "http://zot:.*")'
    e = f'label_replace({e}, "svc", "registry-cache", "instance", "http://dockerhub:.*")'
    e = f'label_replace({e}, "svc", "TLS-Wildcard", "instance", "auth\\\\.lab\\\\..*:443")'
    return e


# --- Bausteine -----------------------------------------------------------------------------
def steps(*pairs):
    """steps("green", 80, "orange", 90, "red") -> Grafana-Threshold-Steps."""
    out = [{"color": pairs[0], "value": None}]
    for i in range(1, len(pairs), 2):
        out.append({"color": pairs[i + 1], "value": pairs[i]})
    return {"mode": "absolute", "steps": out}


def q(expr, legend="", ref=None, instant=False, fmt=None, ds=VM, interval=None):
    t = {"datasource": ds, "expr": expr, "refId": ref, "editorMode": "code"}
    if ds is VM:
        t["legendFormat"] = legend or "__auto"
        t["range"] = not instant
        t["instant"] = instant
    else:
        if legend:
            t["legendFormat"] = legend
        t["queryType"] = "instant" if instant else "range"
    if fmt:
        t["format"] = fmt
    if interval:
        t["interval"] = interval
    return t


def updown(up="UP", down="DOWN"):
    return [{"type": "value", "options": {
        "1": {"text": up, "color": "green", "index": 0},
        "0": {"text": down, "color": "red", "index": 1}}}]


class Dash:
    def __init__(self, uid, title, description, tags=(), variables=(), refresh="1m", time="now-6h"):
        self.uid, self.title, self.description = uid, title, description
        self.tags = ["homelab", *tags]
        self.variables = list(variables)
        self.refresh, self.time = refresh, time
        self.panels = []
        self.x = self.y = self.rowh = 0
        self.next_id = 1

    # Layout: Panels laufen von links nach rechts, bei vollem Raster neue Zeile.
    def _place(self, w, h):
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.rowh
            self.rowh = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.rowh = max(self.rowh, h)
        return pos

    def row(self, title, collapsed=False):
        if self.x:
            self.x, self.y, self.rowh = 0, self.y + self.rowh, 0
        self.panels.append({"type": "row", "title": title, "id": self._id(), "collapsed": collapsed,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.y += 1

    def _id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def panel(self, ptype, title, targets, w, h, *, desc="", unit=None, decimals=None, th=None,
              mappings=None, color=None, minv=None, maxv=None, options=None, custom=None,
              overrides=None, transformations=None, links=None, ds=VM, interval=None, nodata=None):
        for i, t in enumerate(targets):
            t.setdefault("refId", chr(65 + i))
            if t["refId"] is None:
                t["refId"] = chr(65 + i)
        defaults = {}
        if unit:
            defaults["unit"] = unit
        if decimals is not None:
            defaults["decimals"] = decimals
        if th:
            defaults["thresholds"] = th
        if mappings:
            defaults["mappings"] = mappings
        if color:
            defaults["color"] = {"mode": color}
        if minv is not None:
            defaults["min"] = minv
        if maxv is not None:
            defaults["max"] = maxv
        if custom:
            defaults["custom"] = custom
        if links:
            defaults["links"] = links
        if nodata is not None:
            defaults["noValue"] = nodata
        p = {"id": self._id(), "type": ptype, "title": title, "description": desc,
             "datasource": ds, "gridPos": self._place(w, h), "targets": targets,
             "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
             "options": options or {}}
        if transformations:
            p["transformations"] = transformations
        if interval:
            p["interval"] = interval
        self.panels.append(p)
        return p

    # --- häufige Panel-Typen ---
    def stat(self, title, expr, w=3, h=4, *, legend="", graph=True, colormode="value", calc="lastNotNull",
             text="auto", **kw):
        return self.panel("stat", title, [q(expr, legend, instant=not graph)], w, h, options={
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "colorMode": colormode, "graphMode": "area" if graph else "none",
            "justifyMode": "auto", "textMode": text, "orientation": "auto",
            "wideLayout": True, "showPercentChange": False}, **kw)

    def timeseries(self, title, targets, w=12, h=8, *, stack=False, fill=10, bars=False, legend="list",
                   legend_calcs=(), legend_place="bottom", **kw):
        custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "fillOpacity": 80 if bars else fill,
                  "showPoints": "never", "spanNulls": False, "lineInterpolation": "smooth" if not bars else "linear",
                  "gradientMode": "opacity" if not bars else "none",
                  "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                  "axisSoftMin": 0, "insertNulls": False}
        custom.update(kw.pop("custom", {}))
        return self.panel("timeseries", title, targets, w, h, custom=custom, color=kw.pop("color", "palette-classic"),
                          options={"legend": {"displayMode": legend, "placement": legend_place,
                                              "showLegend": legend != "hidden", "calcs": list(legend_calcs)},
                                   "tooltip": {"mode": "multi", "sort": "desc"}}, **kw)

    def bargauge(self, title, targets, w=12, h=8, *, display="gradient", orientation="horizontal", calc="lastNotNull",
                 options_extra=None, **kw):
        options = {
            "reduceOptions": {"calcs": [calc], "fields": "", "values": False},
            "orientation": orientation, "displayMode": display, "valueMode": "color",
            "showUnfilled": True, "namePlacement": "auto", "sizing": "auto", "minVizHeight": 16,
            "maxVizHeight": 300}
        options.update(options_extra or {})
        return self.panel("bargauge", title, targets, w, h, options=options, **kw)

    def text(self, content, w=24, h=3):
        p = {"id": self._id(), "type": "text", "title": "", "gridPos": self._place(w, h),
             "options": {"mode": "markdown", "content": content}}
        self.panels.append(p)
        return p

    def to_json(self):
        return {
            "uid": self.uid, "title": self.title, "description": self.description, "tags": self.tags,
            "editable": False, "graphTooltip": 1, "schemaVersion": 41, "version": 1,
            "timezone": "browser", "weekStart": "monday", "refresh": self.refresh,
            "time": {"from": self.time, "to": "now"}, "timepicker": {},
            "fiscalYearStartMonth": 0, "liveNow": False,
            "links": [{"type": "dashboards", "tags": ["homelab"], "asDropdown": False, "includeVars": False,
                       "keepTime": True, "title": "Homelab", "icon": "external link", "targetBlank": False}],
            "annotations": {"list": [
                {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
                 "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts",
                 "type": "dashboard"},
                {"datasource": VM, "enable": False, "iconColor": "red", "name": "Alerts (firing)",
                 "expr": 'ALERTS{alertstate="firing"}', "step": "60s", "titleFormat": "{{alertname}}",
                 "textFormat": "{{severity}} {{instance}}{{name}}{{mountpoint}}{{zpool}}",
                 "useValueForTime": False, "hide": False},
            ]},
            "templating": {"list": self.variables},
            "panels": self.panels,
        }


def var_query(name, label, query, ds=VM, multi=True, all_=True, regex="", hide=0):
    v = {"name": name, "label": label, "type": "query", "datasource": ds, "refresh": 2, "sort": 1,
         "multi": multi, "includeAll": all_, "hide": hide, "regex": regex,
         "current": {"selected": True, "text": ["All"], "value": ["$__all"]} if all_ else {}}
    if ds is VM:
        v["definition"] = query
        v["query"] = {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery", "qryType": 1}
    else:
        v["definition"] = query
        v["query"] = {"type": 1, "label": query.split("(")[0], "stream": "", "refId": "LokiVariableQueryEditor-VariableQuery"}
    if all_:
        v["allValue"] = ".*"
    return v


def var_loki_label(name, label, lbl, stream):
    return {"name": name, "label": label, "type": "query", "datasource": LOKI, "refresh": 2, "sort": 1,
            "multi": True, "includeAll": True, "allValue": ".*", "hide": 0, "regex": "",
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "definition": f"label_values({stream}, {lbl})",
            "query": {"type": 1, "label": lbl, "stream": stream, "refId": "LokiVariableQueryEditor-VariableQuery"}}


def var_text(name, label, default=""):
    return {"name": name, "label": label, "type": "textbox", "hide": 0, "query": default,
            "current": {"text": default, "value": default}, "options": [{"selected": True, "text": default, "value": default}]}


LINK_LOGS = [{"title": "Logs dieses Containers", "url": "/d/homelab-logs?var-container=${__field.labels.name}&${__url_time_range}"}]
LINK_CT = [{"title": "Container-Details", "url": "/d/homelab-containers?var-container=${__field.labels.name}&${__url_time_range}"}]


# ===========================================================================================
# 1) Übersicht
# ===========================================================================================
def overview():
    d = Dash("homelab-overview", "Homelab · Übersicht",
             "Alles Wichtige auf einen Blick: Dienste, Alerts, NAS-Auslastung, Pools, Backups.",
             tags=["overview"], time="now-24h")
    d.stat("Dienste down", f"count(probe_success{{{PROBE_SERVICES}}} == 0) or vector(0)", graph=False,
           colormode="background", th=steps("green", 1, "red"), desc="Blackbox-Healthchecks mit Status DOWN.")
    d.stat("Aktive Alerts", 'count(ALERTS{alertstate="firing"}) or vector(0)', graph=False,
           colormode="background", th=steps("green", 1, "orange"), desc="Feuernde vmalert-Regeln (config/alerts.yml).")
    d.stat("CPU", f'1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[$__rate_interval]))', unit="percentunit",
           decimals=0, th=steps("green", 0.7, "orange", 0.9, "red"), color="thresholds")
    d.stat("RAM belegt", "1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", unit="percentunit",
           decimals=0, th=steps("green", 0.8, "orange", 0.9, "red"),
           desc="Inkl. ZFS-ARC (zählt unter Linux als belegt, gibt aber bei Bedarf frei).")
    d.stat("Container", f'count(count by (name) (container_last_seen{{name!=""}}))', graph=False,
           th=steps("blue"), desc="Laufende Docker-Container laut cadvisor.")
    d.stat("Uptime NAS", "time() - node_boot_time_seconds", unit="s", decimals=0, graph=False, th=steps("blue"))
    d.stat("Offsite-Backup", 'time() - homelab_backup_last_success_timestamp_seconds{backup="offsite"}',
           unit="s", decimals=0, graph=False, colormode="background",
           th=steps("green", 26 * 3600, "orange", 36 * 3600, "red"), nodata="kein Status",
           desc="Alter des letzten erfolgreichen restic-Laufs nach B2 (backup-offsite.sh, Textfile-Metrik).")
    d.stat("TLS-Zertifikat", 'min(probe_ssl_earliest_cert_expiry{job="probe-tls"}) - time()', unit="s",
           decimals=0, graph=False, colormode="background", th=steps("red", 7 * 86400, "orange", 14 * 86400, "green"),
           desc="Restlaufzeit des Wildcard-Zertifikats (Traefik/ACME).")

    d.row("Dienste & Alerts")
    d.stat("Dienst-Status", svc(f"probe_success{{{PROBE_SERVICES}}}"), w=14, h=7, legend="{{svc}}", graph=False,
           colormode="background", text="value_and_name", mappings=updown(), th=steps("red", 1, "green"),
           desc="Blackbox-Probe je Dienst (intern über die edge-Netze). Details im Dashboard »Dienste«.",
           links=[{"title": "Dienste & Erreichbarkeit", "url": "/d/homelab-services?${__url_time_range}"}])
    alerts_table(d, w=10, h=7)

    d.row("NAS")
    d.timeseries("CPU & RAM", [
        q(f'1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[$__rate_interval]))', "CPU"),
        q("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "RAM"),
        q(f"node_load5 / {CPUS}", "Load5 / Kern"),
    ], w=8, unit="percentunit", minv=0, maxv=1)
    d.bargauge("ZFS-Pools belegt", [q(f"1 - node_filesystem_avail_bytes{{{POOLS}}} / node_filesystem_size_bytes{{{POOLS}}}",
                                      "{{mountpoint}}", instant=True)],
               w=8, unit="percentunit", decimals=1, minv=0, maxv=1, th=steps("green", 0.75, "orange", 0.85, "red"),
               desc="Alert ab 85 % (PoolSpaceLow) bzw. 95 % (PoolSpaceCritical).")
    d.stat("Pool-Zustand", 'max by (zpool) (node_zfs_zpool_state{state="online"})', w=8, h=8, legend="{{zpool}}",
           graph=False, colormode="background", text="value_and_name",
           mappings=updown("ONLINE", "DEGRADED/FAULTED"), th=steps("red", 1, "green"), nodata="keine ZFS-Metriken")

    d.row("Container & Logs")
    d.bargauge("Top-Container RAM", [q(f'topk(10, sum by (name) (container_memory_working_set_bytes{{name!=""}}))',
                                       "{{name}}", instant=True)],
               w=8, unit="bytes", th=steps("blue"), color="continuous-BlPu", links=LINK_CT)
    d.bargauge("Top-Container CPU", [q(f'topk(10, sum by (name) (rate(container_cpu_usage_seconds_total{{name!=""}}[5m])) / {CPUS})',
                                       "{{name}}", instant=True)],
               w=8, unit="percentunit", decimals=1, th=steps("blue"), color="continuous-BlPu", links=LINK_CT,
               desc="Anteil an der gesamten NAS-CPU (alle Kerne = 100 %).")
    d.timeseries("Log-Fehler je Stack", [q(
        f'sum by (compose_project) (count_over_time({{host="truenas"}} |~ "{LOG_ERR}" [$__auto]))',
        "{{compose_project}}", ds=LOKI)], w=8, ds=LOKI, bars=True, stack=True, unit="short",
        desc="Logzeilen mit error/fatal/panic/exception (grobe Heuristik). Details im Dashboard »Logs«.",
        links=[{"title": "Logs", "url": "/d/homelab-logs?${__url_time_range}"}])
    return d


def alerts_table(d, w, h, title="Aktive Alerts"):
    return d.panel("table", title, [q('ALERTS{alertstate="firing"}', instant=True, fmt="table")], w, h,
                   desc="Aktuell feuernde Alerts aus vmalert. Zugestellt per Telegram (Alertmanager).",
                   options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                            "sortBy": [{"displayName": "Schwere", "desc": False}]},
                   custom={"align": "auto", "cellOptions": {"type": "auto"}, "filterable": False},
                   nodata="Keine aktiven Alerts 🎉",
                   overrides=[{"matcher": {"id": "byName", "options": "Schwere"}, "properties": [
                       {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                       {"id": "mappings", "value": [{"type": "value", "options": {
                           "critical": {"color": "red", "index": 0},
                           "warning": {"color": "orange", "index": 1},
                           "info": {"color": "blue", "index": 2}}}]},
                       {"id": "custom.width", "value": 90}]}],
                   transformations=[
                       {"id": "labelsToFields", "options": {"mode": "columns"}},
                       {"id": "organize", "options": {
                           "excludeByName": {"Time": True, "Value": True, "__name__": True, "alertstate": True,
                                             "job": True, "integration": True, "alertgroup": True},
                           "indexByName": {"severity": 0, "alertname": 1, "instance": 2, "name": 3},
                           "renameByName": {"severity": "Schwere", "alertname": "Alert", "instance": "Instanz",
                                            "name": "Container"}}}])


# ===========================================================================================
# 2) NAS-Host
# ===========================================================================================
def nas():
    d = Dash("homelab-nas", "Homelab · NAS-Host",
             "TrueNAS (UGREEN DXP4800 Plus): CPU, RAM inkl. ZFS-ARC, Pools & Datasets, Platten, Temperaturen.",
             tags=["nas"])
    d.stat("Uptime", "time() - node_boot_time_seconds", unit="s", decimals=0, graph=False, th=steps("blue"))
    d.stat("CPU-Kerne", 'count(node_cpu_seconds_total{mode="idle"})', graph=False, th=steps("blue"))
    d.stat("RAM gesamt", "node_memory_MemTotal_bytes", unit="bytes", decimals=0, graph=False, th=steps("blue"))
    d.stat("CPU", f'1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}[$__rate_interval]))', unit="percentunit",
           decimals=0, th=steps("green", 0.7, "orange", 0.9, "red"), color="thresholds")
    d.stat("Load 5 / Kern", f"node_load5 / {CPUS}", decimals=2, th=steps("green", 0.8, "orange", 1.2, "red"),
           color="thresholds", desc="> 1 heißt: mehr lauffähige Prozesse als Kerne.")
    d.stat("RAM verfügbar", "node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", unit="percentunit",
           decimals=0, th=steps("red", 0.1, "orange", 0.2, "green"), color="thresholds",
           desc="Alert HostMemoryLow unter 10 %.")
    d.stat("ZFS-ARC", "sum(node_zfs_arc_size)", unit="bytes", decimals=1, th=steps("purple"), nodata="–")
    d.stat("Max. Temperatur", "max(node_hwmon_temp_celsius)", unit="celsius", decimals=0,
           th=steps("green", 65, "orange", 80, "red"), color="thresholds", nodata="–")

    d.row("CPU")
    d.timeseries("CPU nach Modus", [q(
        f'sum by (mode) (rate(node_cpu_seconds_total{{mode!="idle"}}[$__rate_interval])) / {CPUS}', "{{mode}}")],
        stack=True, unit="percentunit", minv=0, maxv=1,
        desc="iowait hoch = Platten bremsen; steal ist auf Bare-Metal immer 0.")
    d.timeseries("Load", [q("node_load1", "1 min"), q("node_load5", "5 min"), q("node_load15", "15 min"),
                          q(f"{CPUS}", "Kerne")], unit="short",
                 overrides=[{"matcher": {"id": "byName", "options": "Kerne"}, "properties": [
                     {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                     {"id": "custom.fillOpacity", "value": 0}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}])

    d.row("Arbeitsspeicher & ZFS-ARC")
    arc = "scalar(sum(node_zfs_arc_size) or vector(0))"
    d.timeseries("RAM-Aufteilung", [
        q(f"node_memory_MemTotal_bytes - node_memory_MemFree_bytes - node_memory_Buffers_bytes - node_memory_Cached_bytes"
          f" - node_memory_SReclaimable_bytes - {arc}", "Apps & Kernel"),
        q(f"{arc}", "ZFS-ARC"),
        q("node_memory_Buffers_bytes + node_memory_Cached_bytes + node_memory_SReclaimable_bytes", "Page-Cache"),
        q("node_memory_MemFree_bytes", "Frei"),
    ], stack=True, fill=40, unit="bytes", minv=0, legend="table", legend_calcs=("lastNotNull", "max"), legend_place="right",
        desc="Gestapelt = gesamter RAM. ARC und Page-Cache werden bei Bedarf freigegeben.")
    d.timeseries("ARC-Trefferquote", [
        q("sum(rate(node_zfs_arc_hits[$__rate_interval])) / (sum(rate(node_zfs_arc_hits[$__rate_interval])) + sum(rate(node_zfs_arc_misses[$__rate_interval])))", "Hit-Rate"),
    ], w=6, unit="percentunit", maxv=1, desc="Anteil der Lesezugriffe, die aus dem RAM kommen.")
    d.timeseries("ARC-Größe", [q("sum(node_zfs_arc_size)", "aktuell"), q("sum(node_zfs_arc_c)", "Ziel"),
                               q("sum(node_zfs_arc_c_max)", "Maximum")], w=6, unit="bytes")

    d.row("ZFS-Pools & Datasets")
    d.stat("Pool-Zustand", 'max by (zpool) (node_zfs_zpool_state{state="online"})', w=6, h=8, legend="{{zpool}}",
           graph=False, colormode="background", text="value_and_name",
           mappings=updown("ONLINE", "DEGRADED/FAULTED"), th=steps("red", 1, "green"), nodata="keine ZFS-Metriken")
    d.bargauge("Pool-Belegung", [q(f"1 - node_filesystem_avail_bytes{{{POOLS}}} / node_filesystem_size_bytes{{{POOLS}}}",
                                   "{{mountpoint}}", instant=True)],
               w=8, unit="percentunit", decimals=1, minv=0, maxv=1, th=steps("green", 0.75, "orange", 0.85, "red"))
    d.bargauge("Pool frei", [q(f"node_filesystem_avail_bytes{{{POOLS}}}", "{{mountpoint}}", instant=True)],
               w=10, unit="bytes", decimals=1, th=steps("blue"), display="basic")
    d.timeseries("Pool-Belegung über Zeit", [q(
        f"node_filesystem_size_bytes{{{POOLS}}} - node_filesystem_avail_bytes{{{POOLS}}}", "{{mountpoint}}")],
        unit="bytes", desc="Belegte Bytes je Pool. Am besten mit Zeitraum 30 Tage ansehen.")
    d.bargauge("Größte Datasets", [q(
        f"topk(15, node_filesystem_size_bytes{{{DATASETS}}} - node_filesystem_avail_bytes{{{DATASETS}}})",
        "{{mountpoint}}", instant=True)], w=12, unit="bytes", decimals=1, th=steps("blue"), color="continuous-BlPu",
        desc="Belegung je ZFS-Dataset (ohne Snapshots der Kind-Datasets).")

    d.row("Platten")
    d.timeseries("Durchsatz", [
        q(f"rate(node_disk_read_bytes_total{{{DISKS}}}[$__rate_interval])", "{{device}} lesen"),
        q(f"-rate(node_disk_written_bytes_total{{{DISKS}}}[$__rate_interval])", "{{device}} schreiben"),
    ], w=8, unit="Bps", desc="Oben lesen, unten (negativ) schreiben.", custom={"axisSoftMin": None})
    d.timeseries("IOPS", [
        q(f"rate(node_disk_reads_completed_total{{{DISKS}}}[$__rate_interval])", "{{device}} lesen"),
        q(f"-rate(node_disk_writes_completed_total{{{DISKS}}}[$__rate_interval])", "{{device}} schreiben"),
    ], w=8, unit="iops", custom={"axisSoftMin": None})
    d.timeseries("Auslastung", [q(f"rate(node_disk_io_time_seconds_total{{{DISKS}}}[$__rate_interval])", "{{device}}")],
                 w=8, unit="percentunit", maxv=1, desc="Zeitanteil, in dem die Platte beschäftigt war.")

    d.row("Temperaturen")
    d.timeseries("Sensoren", [q("node_hwmon_temp_celsius", "{{chip}} {{sensor}}")], w=24, unit="celsius",
                 legend="table", legend_calcs=("lastNotNull", "max"), legend_place="right",
                 desc="hwmon-Sensoren (CPU, NVMe, drivetemp für SATA-Platten, falls geladen).")
    return d


# ===========================================================================================
# 3) Container & Stacks
# ===========================================================================================
def containers():
    variables = [
        var_query("stack", "Stack", f'label_values(container_last_seen{{name!=""}}, {STACK})'),
        var_query("container", "Container", f'label_values(container_last_seen{{name!="",{STACK}=~"$stack"}}, name)'),
    ]
    d = Dash("homelab-containers", "Homelab · Container & Stacks",
             "Docker-Container auf dem NAS nach Compose-Stack: CPU, RAM gegen mem_limit, Netz, Restarts, OOM.",
             tags=["docker"], variables=variables)
    d.stat("Container", f"count(count by (name) (container_last_seen{{{CT}}}))", graph=False, th=steps("blue"))
    d.stat("CPU gesamt", f"sum(rate(container_cpu_usage_seconds_total{{{CT}}}[$__rate_interval])) / {CPUS}",
           unit="percentunit", decimals=1, th=steps("blue"), desc="Anteil an der NAS-CPU.")
    d.stat("RAM gesamt", f"sum(container_memory_working_set_bytes{{{CT}}})", unit="bytes", decimals=1, th=steps("blue"))
    d.stat("Restarts (24 h)", f"sum(changes(container_start_time_seconds{{{CT}}}[24h])) or vector(0)", graph=False,
           th=steps("green", 1, "orange", 5, "red"), color="thresholds")
    d.stat("OOM-Kills (24 h)", f"sum(increase(container_oom_events_total{{{CT}}}[24h])) or vector(0)", graph=False,
           decimals=0, th=steps("green", 1, "red"), color="thresholds", desc="Container, die ihr mem_limit gesprengt haben.")
    d.stat("Nahe am Limit", f"count(sum by (name) (container_memory_working_set_bytes{{{CT}}}) / "
           f"(sum by (name) (container_spec_memory_limit_bytes{{{CT}}}) > 0) > 0.9) or vector(0)", w=3, graph=False,
           th=steps("green", 1, "orange"), color="thresholds", desc="Container mit über 90 % ihres mem_limit.")
    d.stat("Netz rein", f"sum(rate(container_network_receive_bytes_total{{{CT}}}[$__rate_interval]))", unit="Bps",
           th=steps("blue"))
    d.stat("Netz raus", f"sum(rate(container_network_transmit_bytes_total{{{CT}}}[$__rate_interval]))", unit="Bps",
           th=steps("blue"))

    d.row("Stacks")
    d.timeseries("CPU je Stack", [q(
        f"sum by ({STACK}) (rate(container_cpu_usage_seconds_total{{{CT}}}[$__rate_interval])) / {CPUS}",
        f"{{{{{STACK}}}}}")], stack=True, fill=30, unit="percentunit", minv=0)
    d.timeseries("RAM je Stack", [q(f"sum by ({STACK}) (container_memory_working_set_bytes{{{CT}}})",
                                    f"{{{{{STACK}}}}}")], stack=True, fill=30, unit="bytes", minv=0)

    d.row("Container")
    tbl_q = [
        q(f"sum by (name, {STACK}) (rate(container_cpu_usage_seconds_total{{{CT}}}[5m])) / {CPUS}", instant=True, fmt="table"),
        q(f"sum by (name, {STACK}) (container_memory_working_set_bytes{{{CT}}})", instant=True, fmt="table"),
        q(f"sum by (name, {STACK}) (container_spec_memory_limit_bytes{{{CT}}} > 0)", instant=True, fmt="table"),
        q(f"sum by (name, {STACK}) (container_memory_working_set_bytes{{{CT}}}) / sum by (name, {STACK}) (container_spec_memory_limit_bytes{{{CT}}} > 0)",
          instant=True, fmt="table"),
        q(f"max by (name, {STACK}) (time() - container_start_time_seconds{{{CT}}})", instant=True, fmt="table"),
        q(f"sum by (name, {STACK}) (changes(container_start_time_seconds{{{CT}}}[24h]))", instant=True, fmt="table"),
    ]
    col = lambda n, props: {"matcher": {"id": "byName", "options": n}, "properties": props}
    d.panel("table", "Alle Container", tbl_q, 24, 12,
            desc="Klick auf den Namen: Logs bzw. Details. RAM-Limit leer = kein mem_limit gesetzt.",
            options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                     "sortBy": [{"displayName": "RAM", "desc": True}]},
            custom={"align": "auto", "cellOptions": {"type": "auto"}, "filterable": True},
            transformations=[
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {
                    "excludeByName": {"Time": True},
                    "indexByName": {"name": 0, STACK: 1, "Value #A": 2, "Value #B": 3, "Value #C": 4,
                                    "Value #D": 5, "Value #F": 6, "Value #E": 7},
                    "renameByName": {"name": "Container", STACK: "Stack", "Value #A": "CPU", "Value #B": "RAM",
                                     "Value #C": "RAM-Limit", "Value #D": "% vom Limit", "Value #E": "Läuft seit",
                                     "Value #F": "Restarts 24 h"}}}],
            overrides=[
                col("Container", [{"id": "custom.width", "value": 280}, {"id": "links", "value": [
                    {"title": "Logs dieses Containers", "url": "/d/homelab-logs?var-container=${__value.raw}&${__url_time_range}"},
                    {"title": "Container-Details", "url": "/d/homelab-containers?var-container=${__value.raw}&${__url_time_range}"}]}]),
                col("CPU", [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 1}]),
                col("RAM", [{"id": "unit", "value": "bytes"}, {"id": "decimals", "value": 0}]),
                col("RAM-Limit", [{"id": "unit", "value": "bytes"}, {"id": "decimals", "value": 0}]),
                col("% vom Limit", [{"id": "unit", "value": "percentunit"}, {"id": "min", "value": 0},
                                    {"id": "max", "value": 1},
                                    {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}},
                                    {"id": "thresholds", "value": steps("green", 0.75, "orange", 0.9, "red")}]),
                col("Läuft seit", [{"id": "unit", "value": "s"}, {"id": "decimals", "value": 0}]),
                col("Restarts 24 h", [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                                      {"id": "thresholds", "value": steps("text", 1, "orange", 3, "red")}]),
            ])

    d.timeseries("CPU je Container", [q(
        f"sum by (name) (rate(container_cpu_usage_seconds_total{{{CT}}}[$__rate_interval])) / {CPUS}", "{{name}}")],
        w=24, h=9, unit="percentunit", minv=0, links=LINK_LOGS, legend="table", legend_calcs=("mean", "max"),
        legend_place="right")
    d.timeseries("RAM je Container", [q(f"sum by (name) (container_memory_working_set_bytes{{{CT}}})", "{{name}}")],
                 w=24, h=9, unit="bytes", minv=0, links=LINK_LOGS, legend="table", legend_calcs=("lastNotNull", "max"),
                 legend_place="right",
                 desc="Working-Set (das, was gegen mem_limit zählt).")
    d.timeseries("Netz je Container", [
        q(f"sum by (name) (rate(container_network_receive_bytes_total{{{CT}}}[$__rate_interval]))", "{{name}} rein"),
        q(f"-sum by (name) (rate(container_network_transmit_bytes_total{{{CT}}}[$__rate_interval]))", "{{name}} raus"),
    ], unit="Bps", custom={"axisSoftMin": None}, legend="hidden", desc="Oben empfangen, unten (negativ) gesendet.")
    d.timeseries("Platten-I/O je Container", [
        q(f"sum by (name) (rate(container_fs_reads_bytes_total{{{CT}}}[$__rate_interval]))", "{{name}} lesen"),
        q(f"-sum by (name) (rate(container_fs_writes_bytes_total{{{CT}}}[$__rate_interval]))", "{{name}} schreiben"),
    ], unit="Bps", custom={"axisSoftMin": None}, legend="hidden")
    d.timeseries("Restarts & OOM-Kills", [
        q(f"sum by (name) (changes(container_start_time_seconds{{{CT}}}[$__interval])) > 0", "{{name}} Restart"),
        q(f"sum by (name) (increase(container_oom_events_total{{{CT}}}[$__interval])) > 0", "{{name}} OOM"),
    ], w=24, h=6, bars=True, unit="short", interval="5m",
        desc="Alerts: ContainerRestartLoop (>2 Restarts in 30 min) und ContainerOOMKilled.")
    return d


# ===========================================================================================
# 4) Dienste & Erreichbarkeit
# ===========================================================================================
def services():
    d = Dash("homelab-services", "Homelab · Dienste & Erreichbarkeit",
             "Blackbox-Healthchecks (config/scrape.yml): Status, Verfügbarkeit, Antwortzeiten, TLS, Scrape-Targets.",
             tags=["services"], time="now-24h")
    d.stat("Dienst-Status", svc(f"probe_success{{{PROBE_SERVICES}}}"), w=24, h=5, legend="{{svc}}", graph=False,
           colormode="background", text="value_and_name", mappings=updown(), th=steps("red", 1, "green"))
    d.panel("state-timeline", "Verlauf", [q(svc(f"probe_success{{{PROBE_SERVICES}}}"), "{{svc}}")], 24, 9,
            mappings=updown(), th=steps("red", 1, "green"), color="thresholds",
            custom={"fillOpacity": 80, "lineWidth": 0}, interval="1m",
            options={"showValue": "never", "mergeValues": True, "alignValue": "left", "rowHeight": 0.85,
                     "legend": {"showLegend": False}, "tooltip": {"mode": "single"}})
    d.bargauge("Verfügbarkeit im Zeitraum", [q(svc(f"avg_over_time(probe_success{{{PROBE_SERVICES}}}[$__range])"),
                                               "{{svc}}", instant=True)],
               w=8, h=9, unit="percentunit", decimals=2, minv=0.9, maxv=1, display="basic",
               th=steps("red", 0.99, "orange", 0.999, "green"), desc="Anteil erfolgreicher Probes im gewählten Zeitraum.")
    d.timeseries("Antwortzeit", [q(svc(f"probe_duration_seconds{{{PROBE_SERVICES}}}"), "{{svc}}")], w=16, h=9,
                 unit="s", legend="table", legend_calcs=("mean", "max"), legend_place="right")

    d.row("HTTP & TLS")
    d.stat("HTTP-Status", svc(f"probe_http_status_code{{{PROBE_SERVICES}}}"), w=12, h=6, legend="{{svc}}", graph=False,
           text="value_and_name", colormode="background", th=steps("red", 200, "green", 400, "red"),
           desc="Letzter HTTP-Statuscode je Probe (0 = keine Verbindung).")
    d.stat("Zertifikat läuft ab in", svc('probe_ssl_earliest_cert_expiry{job="probe-tls"} - time()'), w=6, h=6,
           legend="{{svc}}", unit="s", decimals=0, graph=False, colormode="background",
           th=steps("red", 7 * 86400, "orange", 14 * 86400, "green"), desc="Alert CertExpiringSoon unter 14 Tagen.")
    d.stat("TLS-Version", 'probe_tls_version_info{job="probe-tls"}', w=6, h=6, legend="{{version}}", graph=False,
           text="name", th=steps("blue"))

    d.row("Scrape-Targets")
    d.panel("state-timeline", "Exporter erreichbar (up)", [q('up{job!~"probe-.*"}', "{{job}}")], 24, 7,
            mappings=updown(), th=steps("red", 1, "green"), color="thresholds",
            custom={"fillOpacity": 80, "lineWidth": 0}, interval="1m",
            options={"showValue": "never", "mergeValues": True, "alignValue": "left", "rowHeight": 0.85,
                     "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
            desc="Alert TargetDown nach 5 min.")
    d.timeseries("Scrape-Dauer", [q('scrape_duration_seconds{job!~"probe-.*"}', "{{job}}")], w=12, h=7, unit="s")
    d.timeseries("Samples je Scrape", [q('scrape_samples_scraped{job!~"probe-.*"}', "{{job}}")], w=12, h=7,
                 unit="short", desc="Wächst cadvisor stark, steigt die Kardinalität (Speicher in VictoriaMetrics).")
    return d


# ===========================================================================================
# 5) Alerts
# ===========================================================================================
def alerts():
    d = Dash("homelab-alerts", "Homelab · Alerts",
             "vmalert-Regeln (config/alerts.yml), ihr Verlauf und die Zustellkette Alertmanager → Telegram / n8n.",
             tags=["alerts"], time="now-7d")
    d.stat("Critical", 'count(ALERTS{alertstate="firing",severity="critical"}) or vector(0)', graph=False,
           colormode="background", th=steps("green", 1, "red"))
    d.stat("Warning", 'count(ALERTS{alertstate="firing",severity="warning"}) or vector(0)', graph=False,
           colormode="background", th=steps("green", 1, "orange"))
    d.stat("Pending", 'count(ALERTS{alertstate="pending"}) or vector(0)', graph=False, th=steps("text", 1, "yellow"),
           color="thresholds", desc="Bedingung erfüllt, aber 'for' noch nicht abgelaufen.")
    d.stat("Stummgeschaltet", 'sum(alertmanager_silences{state="active"}) or vector(0)', graph=False,
           th=steps("text", 1, "purple"), color="thresholds", desc="Aktive Silences im Alertmanager.")
    d.stat("Regeln", "count(vmalert_alerting_rules_last_evaluation_samples)",
           graph=False, th=steps("blue"), desc="Anzahl geladener Alerting-Regeln.")
    d.stat("Regel-Fehler", "sum(vmalert_alerting_rules_error) or vector(0)", graph=False,
           th=steps("green", 1, "red"), color="thresholds", desc="Regeln, deren letzte Auswertung fehlschlug.")
    d.stat("Zustellung fehlgeschlagen (24 h)", 'sum by (integration) (increase(alertmanager_notifications_failed_total{integration=~"telegram|webhook"}[24h]))',
           w=6, legend="{{integration}}", graph=False, decimals=0, text="value_and_name",
           th=steps("green", 1, "red"), color="thresholds",
           desc="telegram = Alarmierung, webhook = n8n-Alert-Erklärer.")

    d.row("Jetzt")
    alerts_table(d, w=24, h=7)

    d.row("Verlauf")
    d.panel("state-timeline", "Alert-Historie", [q(
        'max by (alertname, severity, instance, name, mountpoint, zpool) (ALERTS{alertstate="firing"})',
        "{{alertname}} {{instance}}{{name}}{{mountpoint}}{{zpool}}")], 24, 10,
        mappings=[{"type": "value", "options": {"1": {"text": "firing", "color": "red", "index": 0}}}],
        color="fixed", custom={"fillOpacity": 80, "lineWidth": 0}, interval="1m",
        options={"showValue": "never", "mergeValues": True, "alignValue": "left", "rowHeight": 0.8,
                 "legend": {"showLegend": False}, "tooltip": {"mode": "single"}},
        desc="Jede Zeile ist ein Alert; Balken = Zeit im Zustand firing. Lücken = gelöst.")
    d.timeseries("Feuernde Alerts nach Schwere", [q('count by (severity) (ALERTS{alertstate="firing"})', "{{severity}}")],
                 stack=True, fill=40, unit="short", interval="5m",
                 overrides=[{"matcher": {"id": "byName", "options": n}, "properties": [
                     {"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
                     for n, c in (("critical", "red"), ("warning", "orange"), ("info", "blue"))])
    d.bargauge("Häufigste Alerts im Zeitraum", [q(
        'sort_desc(sum by (alertname) (count_over_time(ALERTS{alertstate="firing"}[$__range])) * 60)', "{{alertname}}",
        instant=True)], w=12, unit="s", decimals=0, th=steps("orange"), display="basic",
        desc="Summierte Dauer im Zustand firing (Auswertung jede Minute).")

    d.row("Zustellkette")
    d.timeseries("Benachrichtigungen", [
        q('sum by (integration) (increase(alertmanager_notifications_total{integration=~"telegram|webhook"}[$__interval]))', "{{integration}} gesendet"),
        q('sum by (integration) (increase(alertmanager_notifications_failed_total{integration=~"telegram|webhook"}[$__interval]))', "{{integration}} fehlgeschlagen"),
    ], w=12, bars=True, unit="short", interval="10m",
        overrides=[{"matcher": {"id": "byRegexp", "options": ".*fehlgeschlagen"}, "properties": [
            {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}])
    d.timeseries("vmalert: Auswertungen & Fehler", [
        q("sum(rate(vmalert_alerting_rules_errors_total[$__rate_interval]))", "Fehler/s"),
        q("sum(rate(vmalert_iteration_total[$__rate_interval]))", "Iterationen/s"),
    ], w=12, unit="short")
    return d


# ===========================================================================================
# 6) Logs
# ===========================================================================================
def logs():
    stream = '{host="truenas"}'
    variables = [
        var_loki_label("stack", "Stack", "compose_project", stream),
        var_loki_label("container", "Container", "container", '{host="truenas", compose_project=~"$stack"}'),
        var_text("suche", "Suche (Regex)"),
    ]
    d = Dash("homelab-logs", "Homelab · Logs",
             "Container-Logs aller NAS-Stacks (Alloy → Loki). Filter nach Stack, Container und Suchbegriff.",
             tags=["logs"], variables=variables, time="now-1h", refresh="30s")
    sel = f'{LOG_SEL} |~ "(?i)$suche"'
    d.timeseries("Logvolumen", [q(f"sum by (container) (count_over_time({sel} [$__auto]))", "{{container}}", ds=LOKI)],
                 w=16, h=7, ds=LOKI, bars=True, stack=True, unit="short", legend="hidden")
    d.bargauge("Fehler je Container (Zeitraum)", [q(
        f'sum by (container) (count_over_time({LOG_SEL} |~ "{LOG_ERR}" [$__auto]))', "{{container}}", ds=LOKI)],
        w=8, h=7, ds=LOKI, unit="short", decimals=0, minv=0, th=steps("orange"), display="basic",
        options_extra={"reduceOptions": {"values": True, "calcs": [], "fields": "/^Total$/"}},
        transformations=[{"id": "reduce", "options": {"reducers": ["sum"], "mode": "seriesToRows"}},
                         {"id": "sortBy", "options": {"sort": [{"field": "Total", "desc": True}]}},
                         {"id": "limit", "options": {"limitField": 10}}],
        desc="Zeilen mit error/fatal/panic/exception — grobe Heuristik, nicht jedes 'error' ist einer.")
    d.timeseries("Fehler-Zeilen", [q(
        f'sum by (container) (count_over_time({LOG_SEL} |~ "{LOG_ERR}" [$__auto]))', "{{container}}", ds=LOKI)],
        w=24, h=6, ds=LOKI, bars=True, stack=True, unit="short", legend="list")
    d.panel("logs", "Logs", [q(sel, ds=LOKI)], 24, 18, ds=LOKI,
            options={"showTime": True, "showLabels": False, "showCommonLabels": False, "wrapLogMessage": True,
                     "prettifyLogMessage": False, "enableLogDetails": True, "enableInfiniteScrolling": True,
                     "dedupStrategy": "none", "sortOrder": "Descending"},
            desc="Neueste oben. Aufklappen zeigt Labels (container, compose_project, compose_service).")
    return d


DASHBOARDS = [overview, nas, containers, services, alerts, logs]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for build in DASHBOARDS:
        dash = build().to_json()
        path = OUT / f"{dash['uid']}.json"
        wanted.add(path.name)
        path.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {path.relative_to(OUT.parent.parent.parent)}  ({len(dash['panels'])} Panels)")
    for stale in OUT.glob("*.json"):
        if stale.name not in wanted:
            stale.unlink()
            print(f"  entfernt: {stale.name}")


if __name__ == "__main__":
    main()

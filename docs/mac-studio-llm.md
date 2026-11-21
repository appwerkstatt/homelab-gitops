# Mac Studio als LLM-Server (Ollama) für n8n und paperless-ai

Der Mac Studio (`192.168.80.30`, VLAN 80) stellt per **Ollama** lokale Modelle bereit. Nutzer sind
Container auf dem NAS: `13-n8n` und `paperless-ai` (`11-paperless`). Der Mac ist **nicht** von
Arcane verwaltet, deshalb ist das hier ein Runbook zum Abarbeiten von Hand.

Ziel:

1. Ollama läuft dauerhaft, auch ohne angemeldeten Benutzer und nach Stromausfall.
2. Ollama hört im LAN auf Port `11434`, aber **nur das NAS (`192.168.80.50`)** darf zugreifen.
3. Der Mac schläft nie ein.
4. Fällt er trotzdem aus, meldet sich Telegram (Alert `LlmHostDown`) und die Workflows haben einen Plan B.

> **Warum nur das NAS?** Die Ollama-API hat keine Authentifizierung. Wer Port 11434 erreicht, kann
> Modelle laden, löschen und beliebig Rechenzeit verbrauchen. Container auf dem NAS gehen per NAT
> mit der Host-IP `.50` raus, also reicht genau diese eine Quelle für n8n, paperless-ai und den
> blackbox-Probe.

## 0. Ist-Zustand prüfen

paperless-ai nutzt Ollama auf dem Mac schon. Erst schauen, wie es dort heute läuft:

```bash
ollama --version
which ollama                                   # /opt/homebrew/bin/ollama (brew) oder App-Binary
pgrep -lf "ollama serve"                       # läuft es, und als welcher Prozess?
launchctl getenv OLLAMA_HOST                   # App-Variante: so wird das Lauschen im LAN gesetzt
sudo lsof -nP -iTCP:11434 -sTCP:LISTEN         # *:11434 = LAN, 127.0.0.1:11434 = nur lokal
ollama list                                    # vorhandene Modelle
```

In der UniFi-Oberfläche prüfen, dass der Mac Studio eine **feste DHCP-Reservierung auf `.30`** hat
(die IP steht fest in `stacks/11-paperless` und `stacks/13-n8n`).

## 1. Ollama als System-Dienst (LaunchDaemon)

Die Ollama-App startet erst nach dem Login, und `launchctl setenv OLLAMA_HOST` geht beim Neustart
verloren. Robuster ist ein LaunchDaemon, der beim Booten startet.

Falls Ollama noch nicht installiert ist: `brew install ollama`. Läuft bisher die **App**: beenden,
unter *Systemeinstellungen → Allgemein → Anmeldeobjekte* entfernen, damit nicht zwei Instanzen um
Port 11434 streiten. Die App-Binary geht auch (`/Applications/Ollama.app/Contents/Resources/ollama`),
dann den Pfad unten anpassen.

`/Library/LaunchDaemons/org.appsfab.ollama.plist` (Benutzername `christian` ggf. anpassen; die
Modelle bleiben dann unter `~/.ollama/models`, nichts muss neu geladen werden):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>org.appsfab.ollama</string>
  <key>ProgramArguments</key>  <array><string>/opt/homebrew/bin/ollama</string><string>serve</string></array>
  <key>UserName</key>          <string>christian</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>                     <string>/Users/christian</string>
    <!-- 0.0.0.0, nicht die feste IP: beim Booten ist das Netz evtl. noch nicht da. Abschottung macht pf (Schritt 2). -->
    <key>OLLAMA_HOST</key>              <string>0.0.0.0:11434</string>
    <key>OLLAMA_KEEP_ALIVE</key>        <string>30m</string>   <!-- Modell 30 min im RAM halten -->
    <key>OLLAMA_MAX_LOADED_MODELS</key> <string>2</string>     <!-- z. B. Chat-Modell + Embedding parallel -->
    <key>OLLAMA_NUM_PARALLEL</key>      <string>2</string>
    <key>OLLAMA_CONTEXT_LENGTH</key>    <string>16384</string> <!-- Agenten/RAG brauchen mehr als den Default -->
  </dict>
  <key>RunAtLoad</key>         <true/>
  <key>KeepAlive</key>         <true/>
  <key>StandardOutPath</key>   <string>/var/log/ollama.log</string>
  <key>StandardErrorPath</key> <string>/var/log/ollama.log</string>
</dict>
</plist>
```

```bash
sudo chown root:wheel /Library/LaunchDaemons/org.appsfab.ollama.plist
sudo chmod 644 /Library/LaunchDaemons/org.appsfab.ollama.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/org.appsfab.ollama.plist
sudo lsof -nP -iTCP:11434 -sTCP:LISTEN          # erwartet: *:11434
```

Änderungen am plist: `sudo launchctl bootout system/org.appsfab.ollama`, dann wieder `bootstrap`.

Modelle (Beispiele; Größe nach RAM des Mac Studio wählen, als Faustregel braucht ein Q4-Modell
etwa 0,6 GB pro Milliarde Parameter plus Kontext):

```bash
ollama pull qwen2.5:14b          # nutzt paperless-ai schon
ollama pull nomic-embed-text     # Embeddings (paperless-ai, RAG in n8n)
ollama pull llama3.1:8b          # kleines, schnelles Fallback-Modell für n8n
```

## 2. Firewall: nur das NAS darf auf 11434

Die macOS-Anwendungsfirewall kann nur „App darf/darf nicht“, keine Quell-IPs. Deshalb **pf**.
NAS und Mac liegen im selben VLAN, der Verkehr läuft also gar nicht über die UniFi-Firewall —
die Regel muss auf dem Mac sitzen.

`/etc/pf.anchors/org.appsfab.ollama`:

```
# Ollama (11434): nur localhost und das NAS (Container gehen per NAT mit .50 raus)
pass  in quick on lo0 proto tcp from any to any port 11434
pass  in quick proto tcp from 192.168.80.50 to any port 11434
# optional, z. B. Christians Mac im Trusted-VLAN (IP eintragen, dann Zeile aktivieren):
# pass in quick proto tcp from 192.168.10.X to any port 11434
block in quick proto tcp from any to any port 11434
```

In `/etc/pf.conf` **ans Ende** anhängen (macOS-Updates können die Datei zurücksetzen, danach
prüfen):

```
anchor "org.appsfab.ollama"
load anchor "org.appsfab.ollama" from "/etc/pf.anchors/org.appsfab.ollama"
```

pf ist auf macOS beim Booten **nicht** aktiv. Ein zweiter LaunchDaemon schaltet es ein,
`/Library/LaunchDaemons/org.appsfab.pf.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>org.appsfab.pf</string>
  <key>ProgramArguments</key> <array><string>/sbin/pfctl</string><string>-E</string><string>-f</string><string>/etc/pf.conf</string></array>
  <key>RunAtLoad</key>        <true/>
</dict>
</plist>
```

```bash
sudo pfctl -nf /etc/pf.conf                     # Syntax prüfen, ohne zu laden
sudo chown root:wheel /Library/LaunchDaemons/org.appsfab.pf.plist
sudo chmod 644 /Library/LaunchDaemons/org.appsfab.pf.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/org.appsfab.pf.plist
sudo pfctl -s info | head -1                    # "Status: Enabled"
sudo pfctl -a org.appsfab.ollama -s rules       # die drei Regeln von oben
```

Zusätzlich (optional, Verteidigung in der Tiefe): in UniFi eine Regel, die aus **allen anderen
VLANs** TCP `192.168.80.30:11434` verwirft. Das fängt den Fall ab, dass pf nach einem macOS-Update
still aus ist.

## 3. Nie schlafen, nach Stromausfall wieder hochfahren

```bash
sudo pmset -a sleep 0 disksleep 0 standby 0 powernap 0
sudo pmset -a displaysleep 10        # Monitor darf aus, der Rechner nicht
sudo pmset -a womp 1                 # Wake on LAN
sudo pmset -a autorestart 1          # nach Stromausfall automatisch starten
pmset -g                             # prüfen
```

In *Systemeinstellungen → Energie* sollte „Ruhezustand verhindern, wenn der Bildschirm aus ist“
aktiv sein (entspricht `sleep 0`). FileVault verhindert nach einem Neustart den Start bis zur
Passworteingabe — der LaunchDaemon läuft erst danach. Ist FileVault an, bedeutet Stromausfall:
Ollama ist weg, bis jemand das Passwort eingibt (der Alert unten meldet das).

## 4. Prüfen

Vom **NAS** (TrueNAS-Shell):

```bash
curl -s http://192.168.80.30:11434/api/version      # {"version":"..."}
```

Von **einem anderen Gerät** (z. B. Laptop im Trusted-VLAN) muss das scheitern:

```bash
curl -m 5 http://192.168.80.30:11434/api/version    # Timeout = richtig
```

Nach einem Neustart des Mac (ohne Login) nochmal den NAS-Test: Ollama und pf müssen von selbst laufen.

## 5. In n8n nutzen

- Base-URL ist im Stack fest gesetzt (`CREDENTIALS_OVERWRITE_DATA` in `stacks/13-n8n/compose.yaml`):
  im Editor einmal **Credentials → New → Ollama** anlegen, die URL ist schon eingetragen.
- Nodes: *Ollama Chat Model* (für AI Agent / Basic LLM Chain) und *Embeddings Ollama* (RAG).
- Nodes, die nur OpenAI können: Credential *OpenAI* mit Base-URL `http://192.168.80.30:11434/v1`
  und beliebigem API-Key.

## 6. Plan B, wenn der Mac aus ist

- **Alarm:** blackbox probt `http://192.168.80.30:11434/api/version` (Job `probe-llm`); nach 10 min
  ohne Antwort kommt `LlmHostDown` per Telegram.
- **Im Workflow:**
  - Am *AI Agent*-Node **„Fallback Model“** aktivieren und ein zweites Modell anhängen (anderes,
    kleineres Ollama-Modell; oder bewusst ein Cloud-Modell, falls die Daten das erlauben).
  - An LLM-Nodes *Settings → Retry On Fail* (z. B. 3 Versuche, 60 s Abstand) und
    *On Error → Continue (using error output)*, damit der Rest des Workflows weiterläuft bzw. die
    Daten für später liegen bleiben.
  - Für jeden produktiven Workflow einen **Error Workflow** setzen (*Workflow Settings*), der per
    Telegram-Node meldet, welcher Workflow scheiterte.

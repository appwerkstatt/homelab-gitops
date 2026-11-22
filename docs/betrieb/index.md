# Betrieb

| Aufgabe | Seite |
|---|---|
| Änderung ausrollen, Updates, Renovate | [Deploy & Updates](deploy.md) |
| Neuen Dienst hinzufügen | [Neuen Stack anlegen](neuer-stack.md) |
| NAS nach Totalausfall neu aufbauen | [Neuaufbau (DR)](neuaufbau.md) |
| Bekannte Probleme und ihre Lösung | [Fehlersuche](fehlersuche.md) |
| Secret setzen oder rotieren | [Secrets](../sicherheit/secrets.md) |
| Daten zurückholen | [Wiederherstellung](../backup/restore.md) |

## Zugänge

| Was | Wie |
|---|---|
| TrueNAS-UI | `https://192.168.80.50` |
| TrueNAS-Shell | UI → System → Shell (zsh) oder `ssh truenas.server` (= `192.168.80.50`, Benutzer ohne root, `sudo`) |
| Arcane | TrueNAS-App, Link auf der Homepage |
| 1Password-CLI `op` | nur auf Christians Mac |
| Sandbox-VM | `ssh n8n-sandbox` vom Mac (ProxyJump über das NAS) |

!!! tip "TrueNAS-Shell"
    Die Web-Shell ist zsh. Befehle in Variablen (`$CMD`) werden dort nicht wie in bash zerlegt; für
    wiederholte Befehle eine Funktion definieren. Lange Middleware-Aufrufe mit `midclt call -j` als Job starten.

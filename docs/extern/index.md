# Außerhalb des NAS

Geräte und Dienste, die Arcane nicht verwaltet. Für sie gibt es Runbooks zum Abarbeiten von Hand.

| Gerät | Adresse | Rolle | Doku |
|---|---|---|---|
| Mac Studio | `192.168.80.30` | Ollama (`:11434`) für paperless-ai und n8n-Workflows, LM Studio (`:1234`) für den n8n-Assistenten | [Runbook](../mac-studio-llm.md) |
| VM `n8n-sandbox` | `10.88.88.2` (an `br88`) | Code-Sandbox des n8n-Assistenten | [n8n-Sandbox](n8n-sandbox.md) |
| Pi-Cluster | `192.168.80.41–.44`, `.51–.54` | Kubernetes-Lernumgebung | [Cluster](cluster.md) |
| Home Assistant | eigener Raspberry Pi 5 (IP noch nicht dokumentiert) | Hausautomation, läuft unabhängig vom NAS | – |
| Christians Mac | Trusted-VLAN | Arbeitsplatz: 1Password-CLI, SSH, Pushes nach Forgejo | – |

Der Mac Studio braucht eine feste DHCP-Reservierung auf `.30`, weil die Adresse in mehreren Stacks fest steht.

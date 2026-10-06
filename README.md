# Amazon Bestellungen für Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Zeigt deine aktuellen Amazon-Bestellungen in Home Assistant an. Bestellungen, die
**länger als 7 Tage zugestellt** sind, verschwinden automatisch aus der Liste
(die Anzahl Tage ist einstellbar).

> ⚠️ Amazon bietet keine offizielle API für Bestellungen. Die Integration meldet sich
> wie ein Browser an und liest die Bestellübersicht aus. Ändert Amazon das Layout
> der Seite, kann ein Update der Integration nötig sein.

## Installation über HACS

1. HACS → ⋮ → **Benutzerdefinierte Repositories** →
   `https://github.com/mcjoin/HaAmazonOrders`, Typ **Integration** hinzufügen.
2. „Amazon Bestellungen“ in HACS suchen und installieren.
3. Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Amazon Bestellungen**.

Updates erscheinen automatisch in HACS, sobald ein neues GitHub-Release veröffentlicht wird.

## Einrichtung

| Feld | Beschreibung |
|---|---|
| Amazon-Seite | z. B. `amazon.de` |
| E-Mail / Passwort | Zugangsdaten deines Amazon-Kontos |
| 2FA-Schlüssel (optional) | Wenn die Zwei-Schritt-Verifizierung per Authenticator-App aktiv ist, kannst du hier den Schlüssel eintragen (Amazon → Anmelden & Sicherheit → Zwei-Schritt-Verifizierung → neue App hinzufügen → „Kann den Barcode nicht scannen?“). Dann kann sich die Integration jederzeit selbst neu anmelden. Ohne Schlüssel wirst du bei der Einrichtung nach dem Code (SMS/App) gefragt. |

Wenn die Anmeldung abläuft und ein Code nötig ist, meldet Home Assistant eine
**erneute Authentifizierung**.

### Optionen

- **Zugestellte Bestellungen anzeigen für (Tage)** – Standard 7
- **Abfrageintervall** – Standard 30 Minuten (bitte nicht zu niedrig wählen)
- **Max. Seiten** – wie viele Seiten (à 10 Bestellungen) der letzten 3 Monate gelesen werden

## Entitäten

| Entität | Zustand | Attribut `orders` |
|---|---|---|
| `sensor.amazon_…_bestellungen` | Anzahl angezeigter Bestellungen | alle Bestellungen (offen + kürzlich zugestellt) |
| `sensor.amazon_…_unterwegs` | Anzahl noch nicht zugestellter Bestellungen | nur offene Bestellungen |

Jede Bestellung enthält: `order_id`, `order_date`, `total`, `url`, `items`,
`status`, `delivered`, `delivered_on`, `remove_after`.

### Beispiel-Karte (Markdown)

```yaml
type: markdown
title: Amazon Bestellungen
content: >
  {% for o in state_attr('sensor.amazon_bestellungen', 'orders') or [] %}
  **{{ o.items | join(', ') | truncate(80) }}**  
  {{ o.status }} · [{{ o.order_id }}]({{ o.url }})

  {% else %}
  Keine Bestellungen.
  {% endfor %}
```

## Release erstellen (für Entwickler)

1. Auf GitHub ein Release mit Tag z. B. `v0.1.0` veröffentlichen – der Workflow
   setzt die Version im Manifest und hängt `amazon_bestellungen.zip` an. HACS bietet
   das Update dann automatisch an.

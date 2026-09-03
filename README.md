# MTG Lore Bot

Ein Discord-Bot, der https://magic.wizards.com/en/story auf neue Story-Episoden
prüft und sie komplett in einen Textchannel postet: Titel-Embed mit Cover-Bild
und Teaser, der volle Story-Text in schön formatierten Blöcken, Story-Artworks
und Kartenvorschauen (via Scryfall) genau an der Stelle, wo sie in der
Original-Story stehen.

**Prüf-Rhythmus:** normal alle 30 Minuten, täglich zwischen 16:55 und 18:00 Uhr
deutscher Zeit (übliche Release-Zeit) jede Minute. Anpassbar oben in `bot.py`.

**Slash-Commands:** `/teststory` postet die neueste Episode sofort (zum Testen),
`/storycheck` prüft sofort auf neue Episoden.

---

## Was man immer braucht: einen Bot-Token + Channel-ID

Der Token ist der „Schlüssel" zu einem Discord-Bot-Account. Er steckt **nicht**
im Code und **nicht** im Docker-Image – man gibt ihn erst beim Starten an.
Jeder kann sich kostenlos einen eigenen Bot erstellen:

1. https://discord.com/developers/applications → **New Application** → Name vergeben
2. Links auf **Bot** → **Reset Token** → Token kopieren (gut aufheben, niemandem zeigen!)
3. Einladen: **OAuth2 → URL Generator** → Haken bei `bot` + `applications.commands`,
   Permissions: *Send Messages* und *Embed Links* → generierte URL öffnen → Server auswählen
4. Channel-ID: In Discord den Entwicklermodus aktivieren (Einstellungen → Erweitert),
   dann Rechtsklick auf den Ziel-Channel → **ID kopieren**

> ⚠️ Den Token niemals committen oder in einen Discord-Channel posten –
> Discord macht öffentlich gepostete Tokens automatisch ungültig.

---

## Variante A: Direkt mit Python starten (z. B. auf dem eigenen PC)

```
pip install -r requirements.txt
```

Dann `config.json` anlegen (oder die vorhandene bearbeiten):

```json
{
  "discord_token": "DEIN_TOKEN",
  "channel_id": "DEINE_CHANNEL_ID"
}
```

Starten mit `python bot.py` (Windows: Doppelklick auf `start.bat`).

## Variante B: Als Docker-Container (empfohlen für Server)

### Woher kommt das Image?

Das baut GitHub automatisch: Der Workflow in
[`.github/workflows/docker.yml`](.github/workflows/docker.yml) läuft bei jedem
Push auf `main`, baut das Docker-Image und veröffentlicht es kostenlos in der
GitHub Container Registry (GHCR). Man muss nichts selbst bauen – einfach pullen:

```
docker pull ghcr.io/fhagedorn/mtg-lore-bot:latest
```

(Fortschritt der Builds: Tab **Actions** in diesem Repo.)

### Starten

1. Einen Ordner auf dem Server anlegen und die
   [`docker-compose.yml`](docker-compose.yml) aus diesem Repo hineinlegen.
   Darin die Zeile `build: .` durch das fertige Image ersetzen:

   ```yaml
   image: ghcr.io/fhagedorn/mtg-lore-bot:latest
   ```

2. Im selben Ordner eine Datei `.env` anlegen – **hier kommt der Token rein**:

   ```
   DISCORD_TOKEN=DEIN_TOKEN
   CHANNEL_ID=DEINE_CHANNEL_ID
   ```

3. Starten:

   ```
   docker compose up -d
   ```

Das war's. `restart: unless-stopped` sorgt dafür, dass der Bot auch nach einem
Server-Neustart automatisch wieder läuft.

**Nützliche Befehle:**

| Befehl | Zweck |
|---|---|
| `docker logs -f mtg-story-bot` | Live-Logs anschauen |
| `docker compose pull && docker compose up -d` | Auf neueste Version updaten |
| `docker compose down` | Bot stoppen |

Der Merkzustand (welche Stories schon gepostet wurden) liegt im Unterordner
`./data` und überlebt Updates und Neustarts.

---

## Gut zu wissen

- **Beim allerersten Start** werden alle aktuell vorhandenen Stories nur als
  „gelesen" markiert (kein Spam). Ab dann wird jede neue Episode automatisch gepostet.
- **Nur eine Instanz gleichzeitig** laufen lassen – sonst wird doppelt gepostet.
- `data/seen.json` löschen = Bot vergisst alles und postet beim nächsten Check
  alle Episoden der Seite neu.
- Wie der Bot Neues erkennt: Er vergleicht die Story-Links auf der Seite mit
  seiner Merkliste – jeder unbekannte Link gilt als neue Story.

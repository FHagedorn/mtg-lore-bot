# MTG Story Discord Bot

Prüft https://magic.wizards.com/en/story auf neue Story-Episoden und postet sie
in deinen Discord-Channel: ein hübsches Embed mit Bild + Teaser, und der komplette
Story-Text landet gut lesbar in einem Thread darunter – inklusive aller
Story-Artworks und Kartenvorschauen (via Scryfall) an der richtigen Stelle im Text.

**Prüf-Rhythmus:** normal alle 30 Minuten, aber täglich zwischen 16:55 und 18:00 Uhr
(übliche Release-Zeit) jede Minute. Anpassbar oben in `bot.py`
(`FAST_WINDOW_START` / `FAST_WINDOW_END` / `NORMAL_INTERVAL_MINUTES`).

## Checkliste (einmalig)

1. **Bot erstellen:** https://discord.com/developers/applications → "New Application" → Name vergeben
2. Links auf **"Bot"** klicken → **"Reset Token"** → Token kopieren
3. Token in `config.json` bei `discord_token` eintragen
4. **Bot einladen:** Links auf "OAuth2" → "URL Generator" → Haken bei `bot` und `applications.commands`
   → unten bei Bot Permissions: `Send Messages`, `Embed Links`, `Create Public Threads`, `Send Messages in Threads`
   → generierte URL öffnen und Bot auf deinen Server einladen
5. **Channel-ID holen:** In Discord unter Einstellungen → Erweitert → "Entwicklermodus" aktivieren,
   dann Rechtsklick auf den Ziel-Channel → "ID kopieren" → in `config.json` bei `channel_id` eintragen
6. Doppelklick auf `start.bat` (oder `python bot.py` im Terminal)

## Testen

- `/teststory` im Discord eingeben → postet die neueste Story sofort (auch wenn schon gesehen)
- `/storycheck` → prüft sofort auf neue Stories

## Mit Docker laufen lassen (z. B. auf einem Server)

Das GitHub-Actions-Workflow in `.github/workflows/docker.yml` baut bei jedem Push
auf `main` automatisch ein Image und veröffentlicht es auf GHCR.

**Image pullen und starten:**

```bash
docker pull ghcr.io/BESITZER/mtg-story-bot:latest
```

Dann eine `.env`-Datei anlegen (siehe `.env.example`) mit `DISCORD_TOKEN` und
`CHANNEL_ID`, dazu die `docker-compose.yml` aus diesem Repo, und:

```bash
docker compose up -d
```

(In der `docker-compose.yml` dafür die `build: .`-Zeile durch
`image: ghcr.io/BESITZER/mtg-story-bot:latest` ersetzen.)

Logs anschauen: `docker logs -f mtg-story-bot` ·
Der Merkzustand (`seen.json`) liegt im Ordner `./data` neben der Compose-Datei.

## Wichtig zu wissen

- **Beim allerersten Start** werden alle aktuell vorhandenen Stories nur als "gelesen" markiert
  (damit der Channel nicht zugespammt wird). Ab dann wird jede neue Episode automatisch gepostet.
- Gemerkte Stories stehen in `seen.json` – Datei löschen = alles gilt wieder als neu.
- Der Bot muss laufen, damit er posten kann (Fenster offen lassen oder auf einem Server/Raspberry Pi laufen lassen).
- Prüf-Intervall ändern: `CHECK_INTERVAL_MINUTES` oben in `bot.py`.

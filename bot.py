"""
MTG Story Discord Bot
Prüft regelmäßig https://magic.wizards.com/en/story auf neue Story-Episoden
und postet sie gut lesbar in einen Discord-Textchannel (als Embed + Thread mit Volltext).
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import discord
from bs4 import BeautifulSoup, NavigableString, Tag
from discord.ext import tasks

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
# Im Docker-Container zeigt DATA_DIR auf ein Volume, damit seen.json Neustarts überlebt
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
SEEN_FILE = DATA_DIR / "seen.json"

BASE_URL = "https://magic.wizards.com"
# Das News-Archiv ist die zuverlässigste Quelle: Es listet neue Episoden sofort
# (die Story-Hub-Seite hängt manchmal hinterher) und lässt sich per Kategorie
# fein filtern (z. B. magic-story, announcements, feature, making-magic).
ARCHIVE_CATEGORY = os.environ.get("STORY_CATEGORY", "magic-story")
ARCHIVE_URL = f"{BASE_URL}/en/news/archive?category={ARCHIVE_CATEGORY}&page=1"

# Normal wird alle 30 Minuten geprüft. Im Release-Fenster (Stories kommen
# ca. 17:00 Uhr raus) wird jede Minute geprüft. Zeiten = deutsche Zeit,
# egal in welcher Zeitzone der Rechner/Server steht.
TIMEZONE = ZoneInfo("Europe/Berlin")
NORMAL_INTERVAL_MINUTES = 30
FAST_WINDOW_START = (16, 55)  # (Stunde, Minute)
FAST_WINDOW_END = (18, 0)

HEADERS = {"User-Agent": "Mozilla/5.0 (MTG-Story-Discord-Bot)"}

# Konfiguration: Umgebungsvariablen (Docker) haben Vorrang vor config.json
config = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
TOKEN = os.environ.get("DISCORD_TOKEN") or config.get("discord_token", "")
try:
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID") or config.get("channel_id", 0))
except ValueError:
    CHANNEL_ID = 0  # noch nicht konfiguriert

if not TOKEN or TOKEN.startswith("HIER_"):
    raise SystemExit("Kein Discord-Token gesetzt! Entweder in config.json eintragen "
                     "oder Umgebungsvariable DISCORD_TOKEN setzen.")


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

async def fetch_html(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers=HEADERS) as resp:
        resp.raise_for_status()
        return await resp.text()


async def get_story_links(session: aiohttp.ClientSession) -> list[str]:
    """Liefert die Story-Artikel-URLs aus dem News-Archiv, neueste zuerst."""
    html = await fetch_html(session, ARCHIVE_URL)
    links = re.findall(rf'href="(/en/news/{re.escape(ARCHIVE_CATEGORY)}/[^"]+)"', html)
    result = []
    for link in links:
        url = BASE_URL + link
        if url not in result:
            result.append(url)
    return result


# Platzhalter, die beim Posten in echte Bilder aufgelöst werden
IMG_MARKER = "@@IMG@@{url}@@END@@"
CARD_MARKER = "@@CARD@@{name}@@END@@"
IMG_RE = re.compile(r"@@IMG@@(.*?)@@END@@")
CARD_RE = re.compile(r"@@CARD@@(.*?)@@END@@")


def _node_to_markdown(node) -> str:
    """Wandelt einen HTML-Knoten des Artikels in Discord-Markdown um."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""

    if node.name in ("script", "style", "aside", "footer", "iframe", "svg", "cig-card"):
        return ""

    if node.name == "img":
        src = node.get("src", "")
        return f"\n\n{IMG_MARKER.format(url=src)}\n\n" if src.startswith("http") else ""

    inner = "".join(_node_to_markdown(c) for c in node.children)

    if node.name == "auto-card":
        name = inner.strip()
        return f"**{name}**{CARD_MARKER.format(name=name)}" if name else ""
    if node.name == "figure":
        return inner

    if node.name in ("em", "i"):
        stripped = inner.strip()
        return f"*{stripped}*" if stripped else ""
    if node.name in ("strong", "b"):
        stripped = inner.strip()
        return f"**{stripped}**" if stripped else ""
    if node.name in ("h1", "h2", "h3", "h4"):
        stripped = inner.strip()
        return f"\n\n**__{stripped}__**\n\n" if stripped else ""
    if node.name == "hr":
        return "\n\n⸻ ⸻ ⸻\n\n"
    if node.name == "li":
        return f"• {inner.strip()}\n"
    if node.name == "p":
        stripped = inner.strip()
        return f"{stripped}\n\n" if stripped else ""
    if node.name in ("ul", "ol", "div", "section", "article"):
        return inner
    if node.name == "br":
        return "\n"
    if node.name == "a":
        return inner  # nur Text behalten, Kartenlinks erzeugen sonst Chaos
    return inner


def parse_article(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    og = lambda prop: (soup.find("meta", property=prop) or {}).get("content")
    title = og("og:title") or (soup.title.string if soup.title else url)
    description = og("og:description") or ""
    image = og("og:image")

    body_div = soup.select_one("div.article-body")
    text = ""
    if body_div:
        text = _node_to_markdown(body_div)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return {"url": url, "title": title.strip(), "description": description.strip(),
            "image": image, "text": text}


def chunk_text(text: str, limit: int = 1900) -> list[str]:
    """Teilt den Story-Text an Absatzgrenzen in Discord-taugliche Häppchen."""
    chunks, current = [], ""
    for para in text.split("\n\n"):
        # Einzelabsatz zu lang? Hart an Satzgrenzen teilen.
        while len(para) > limit:
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > 0 else limit
            piece, para = para[:cut], para[cut:].lstrip()
            if len(current) + len(piece) + 2 > limit:
                if current:
                    chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
        if len(current) + len(para) + 2 > limit:
            if current:
                chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Discord-Bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


_card_image_cache: dict[str, str | None] = {}


async def get_card_image(session: aiohttp.ClientSession, name: str) -> str | None:
    """Holt das Kartenbild über die Scryfall-API (mit Cache)."""
    if name in _card_image_cache:
        return _card_image_cache[name]
    url = None
    try:
        async with session.get("https://api.scryfall.com/cards/named",
                               params={"fuzzy": name}, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "image_uris" in data:
                    url = data["image_uris"].get("normal")
                elif data.get("card_faces"):
                    url = data["card_faces"][0].get("image_uris", {}).get("normal")
    except Exception as e:
        print(f"[Scryfall] Fehler bei '{name}': {e!r}")
    _card_image_cache[name] = url
    return url


STORY_COLOR = discord.Color.from_str("#f5a623")


async def post_story(channel: discord.TextChannel, article: dict,
                     session: aiohttp.ClientSession) -> None:
    """Postet das Titel-Embed in den Channel und die komplette Story
    (Text-Blöcke, Story-Artworks, Kartenvorschauen in Original-Reihenfolge)
    in einen Thread darunter."""
    header = discord.Embed(
        title=f"📖 {article['title']}",
        description=f"*{article['description']}*" if article["description"] else None,
        url=article["url"],
        color=STORY_COLOR,
    )
    if article["image"]:
        header.set_image(url=article["image"])
    header.set_author(name="Magic: The Gathering – Neue Story!")
    header_msg = await channel.send(embed=header)

    if not article["text"]:
        return

    # Kompletter Inhalt in einen Thread, damit der Channel übersichtlich bleibt
    try:
        channel = await header_msg.create_thread(
            name=article["title"][:100], auto_archive_duration=10080
        )
    except discord.HTTPException as e:
        print(f"[Post] Thread konnte nicht erstellt werden ({e}), poste in den Channel.")

    # Text an Bild-Platzhaltern in Segmente teilen: Text, Bild, Text, ...
    segments = IMG_RE.split(article["text"])  # ungerade Indizes = Bild-URLs
    for i, segment in enumerate(segments):
        if i % 2 == 1:  # Story-Artwork als Bild-Embed
            art_embed = discord.Embed(color=STORY_COLOR)
            art_embed.set_image(url=segment)
            await channel.send(embed=art_embed)
            continue
        for chunk in chunk_text(segment.strip(), limit=4000):
            card_names = list(dict.fromkeys(CARD_RE.findall(chunk)))
            chunk = CARD_RE.sub("", chunk).strip()
            if chunk:
                await channel.send(embed=discord.Embed(description=chunk,
                                                       color=STORY_COLOR))
            # Kartenvorschau(en) direkt nach dem Abschnitt posten
            for name in card_names:
                img = await get_card_image(session, name)
                if img:
                    card_embed = discord.Embed(color=STORY_COLOR)
                    card_embed.set_image(url=img)
                    card_embed.set_footer(text=f"🃏 {name}")
                    await channel.send(embed=card_embed)

    outro = discord.Embed(
        description=f"✨ *Ende der Episode* – [Auf der Website lesen]({article['url']})",
        color=STORY_COLOR,
    )
    await channel.send(embed=outro)


async def check_for_new_stories() -> str:
    ch = client.get_channel(CHANNEL_ID)
    if ch is None:
        return "Channel nicht gefunden – stimmt die channel_id in der Konfiguration?"

    seen = load_seen()
    async with aiohttp.ClientSession() as session:
        links = await get_story_links(session)
        if not links:
            return "Keine Story-Links auf der Seite gefunden."

        if not SEEN_FILE.exists():
            # Erster Start: alles als gesehen markieren, nichts spammen
            save_seen(set(links))
            return (f"Erster Start: {len(links)} vorhandene Stories als gelesen markiert. "
                    f"Ab jetzt werden nur neue Stories gepostet.")

        new_links = [l for l in links if l not in seen]
        posted = 0
        for url in reversed(new_links):  # Archiv listet neueste zuerst → umdrehen
            html = await fetch_html(session, url)
            article = parse_article(html, url)
            await post_story(ch, article, session)
            seen.add(url)
            save_seen(seen)  # sofort speichern, falls mittendrin was schiefgeht
            posted += 1

        return f"{posted} Story/Stories gepostet." if posted else "Nichts Neues."


async def post_latest_story(channel: discord.abc.Messageable) -> str:
    """Für /teststory: Postet immer genau die neueste Episode – egal ob schon gesehen."""
    async with aiohttp.ClientSession() as session:
        links = await get_story_links(session)
        if not links:
            return "Keine Story-Links auf der Seite gefunden."
        url = links[0]  # Archiv listet neueste zuerst
        article = parse_article(await fetch_html(session, url), url)
        await post_story(channel, article, session)
        seen = load_seen()
        seen.add(url)
        save_seen(seen)
        return f"Neueste Story gepostet: {article['title']}"


def in_fast_window() -> bool:
    now = datetime.now(TIMEZONE)
    return FAST_WINDOW_START <= (now.hour, now.minute) < FAST_WINDOW_END


_last_check: datetime | None = None


@tasks.loop(minutes=1)
async def story_check_loop():
    global _last_check
    now = datetime.now(TIMEZONE)
    if not in_fast_window():
        if _last_check and (now - _last_check) < timedelta(minutes=NORMAL_INTERVAL_MINUTES):
            return
    _last_check = now
    try:
        result = await check_for_new_stories()
        print(f"[Check {now:%H:%M}{' ⚡' if in_fast_window() else ''}] {result}")
    except Exception as e:
        print(f"[Check {now:%H:%M}] Fehler: {e!r}")


@story_check_loop.before_loop
async def before_loop():
    await client.wait_until_ready()


@tree.command(name="teststory", description="Postet die neueste Magic-Story zum Testen")
async def teststory(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        result = await post_latest_story(interaction.channel)
        await interaction.followup.send(f"✅ {result}")
    except Exception as e:
        await interaction.followup.send(f"❌ Fehler: {e!r}")


@tree.command(name="storycheck", description="Prüft sofort auf neue Magic-Stories")
async def storycheck(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        result = await check_for_new_stories()
        await interaction.followup.send(f"✅ {result}")
    except Exception as e:
        await interaction.followup.send(f"❌ Fehler: {e!r}")


@client.event
async def on_ready():
    await tree.sync()
    print(f"Eingeloggt als {client.user} – prüfe alle {NORMAL_INTERVAL_MINUTES} Min., "
          f"zwischen {FAST_WINDOW_START[0]}:{FAST_WINDOW_START[1]:02d} und "
          f"{FAST_WINDOW_END[0]}:{FAST_WINDOW_END[1]:02d} Uhr jede Minute.")
    if not story_check_loop.is_running():
        story_check_loop.start()


if __name__ == "__main__":
    client.run(TOKEN)

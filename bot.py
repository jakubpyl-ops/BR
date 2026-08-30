import os
import re
import json
import asyncio
import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import discord
from discord.ext import commands, tasks
from discord import app_commands

# Biblioteka do łączenia się z serwerem Minecraft przez RCON.
# Zainstaluj ją na serwerze, na którym stoi bot: pip install mcrcon --break-system-packages
try:
    from mcrcon import MCRcon
    # mcrcon w konstruktorze/odczycie ustawia timeout przez signal.signal()/signal.alarm(),
    # a to działa wyłącznie w głównym wątku głównego interpretera. My łączymy się przez
    # asyncio.to_thread (wątek roboczy), więc wyłączamy te wywołania i pilnujemy timeoutu
    # samym socketem (patrz rcon_wykonaj -> mcr.socket.settimeout(...)).
    import mcrcon as _mcrcon_module
    if hasattr(_mcrcon_module, "signal") and _mcrcon_module.signal is not None:
        _mcrcon_module.signal.signal = lambda *args, **kwargs: None
        _mcrcon_module.signal.alarm = lambda *args, **kwargs: None
except ImportError:
    MCRcon = None

# ========================
#   ZMIENNE ŚRODOWISKOWE (ustawiasz raz, przy hostingu)
# ========================

TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")  # na Railway z Volume: /data/config.json
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "1504159576918982747"))

# Strefa czasowa, wg której liczone są godziny automatycznej wysyłki (np. Igrzysk).
# Dzięki temu godziny w panelu (np. 18:00) to zawsze realny czas polski,
# niezależnie od tego, w jakiej strefie stoi serwer, na którym hostowany jest bot
# (a hosting jak Railway zwykle działa w UTC, stąd wcześniejsze przesunięcie o 2h).
STREFA_CZASOWA = ZoneInfo("Europe/Warsaw")

# Obrazki (banery) zapisujemy jako pliki obok config.json, a nie jako linki -
# linki z Discord CDN wygasają po jakimś czasie (mają podpis czasowy w URL),
# a lokalny plik wysyłany na nowo za każdym razem nigdy nie wygasa.
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), "obrazki")
os.makedirs(IMAGES_DIR, exist_ok=True)

# Poniższe to tylko "seed" na pierwsze uruchomienie - później WSZYSTKO
# konfigurujesz komendami /konfiguracja na Discordzie i zapisuje się do config.json
_SEED_WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
_SEED_GOODBYE_CHANNEL_ID = int(os.getenv("GOODBYE_CHANNEL_ID", "0"))
_SEED_TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
_SEED_STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
_SEED_VERIFY_ROLE_ID = int(os.getenv("VERIFY_ROLE_ID", "0"))

# ========================
#   DOMYŚLNA KONFIGURACJA (edytowalna z Discorda, zapisywana w JSON)
# ========================

DEFAULT_CONFIG = {
    "images": {
        "powitanie": "",
        "pozegnanie": "",
        "ticket": "",
        "ticket_wiadomosc": "",
        "weryfikacja": "",
        "propozycja": "",
    },
    "colors": {
        "powitanie": "#57F287",   # zielony
        "pozegnanie": "#ED4245",  # czerwony
        "akcent": "#E74C3C",      # kolor ticketów / regulaminu / weryfikacji
    },
    "channels": {
        "powitanie": 0,
        "pozegnanie": 0,
        "ticket_panel": 0,
        "weryfikacja": 0,
        "propozycje": 0,
    },
    "propozycje_glosy": {},
    "igrzyska": {
        "kanal_zapowiedzi": 0,
        "kanal_ogloszenia": 0,
        "wiadomosc_zapowiedz_tytul": "🏹 Igrzyska Śmierci już wkrótce!",
        "wiadomosc_zapowiedz_tresc": (
            "Zbieramy chętnych na najbliższe Igrzyska Śmierci!\n\n"
            "Zareaguj {emoji} pod tą wiadomością, żeby zgłosić chęć udziału.\n"
            "Gdy zbierzemy **{wymagane}** reakcji, lobby zostanie otwarte automatycznie!"
        ),
        "wiadomosc_start_tresc": (
            "🎉 Zebraliśmy wystarczająco chętnych! Lobby Igrzysk Śmierci jest **otwarte**!\n"
            "Dołączcie jak najszybciej - zapisy zamkną się za **10 minut**."
        ),
        "wiadomosc_zamkniecie_tresc": "🔒 Zapisy do Igrzysk Śmierci zostały zamknięte. Powodzenia dla uczestników!",
        "emoji_reakcja": "🎉",
        "wymagane_reakcje": 15,
        "godziny": ["18:00"],
        "harmonogram_aktywny": False,
        "rcon_host": "",
        "rcon_port": 25575,
        "rcon_haslo": "",
        "komenda_start": "igrzyska start-lobby",
        "komenda_zamknij": "igrzyska zamknij-lobby",
        "aktualna_wiadomosc_id": 0,
        "aktualny_kanal_id": 0,
        "w_trakcie": False,
        "ostatnio_wyslane": [],
        # Pingowanie przy wysyłce zapowiedzi: "brak" / "rola" / "everyone"
        "typ_ping": "brak",
        "rola_ping_id": 0,
        # Pingowanie przy ogłoszeniu startu lobby: "brak" / "rola" / "everyone"
        # (domyślnie "everyone", żeby zachować dotychczasowe zachowanie bota)
        "typ_ping_start": "everyone",
        "rola_ping_start_id": 0,
    },
    "panel_messages": {
        "ticket": {"channel_id": 0, "message_id": 0},
        "weryfikacja": {"channel_id": 0, "message_id": 0},
    },
    "roles": {
        "staff": 0,
        "weryfikacja": 0,
    },
    "ticket_category_id": 0,
    "weryfikacja_tytul": "Weryfikacja",
    "weryfikacja_opis": "Kliknij przycisk poniżej, aby zweryfikować się i uzyskać dostęp do serwera.",
    "ticket_wiadomosc_tresc": "Witaj na swoim zgłoszeniu! Ticket został utworzony przez {mention}.",
    "ticket_zasady_tekst": (
        "**Cierpliwość:** Prosimy cierpliwie poczekać na {rola}! Nie tylko Ty czekasz na pomoc. "
        "Maksymalny czas oczekiwania na sprawdzenie zgłoszenia to **24h**.\n"
        "**Nie oznaczaj** {rola} więcej niż raz - zbyt wiele oznaczeń może skutkować ograniczeniem uprawnień."
    ),
    "regulamin": (
        "**Regulamin FFA**\n\n"
        "Przeczytaj zasady przed rozpoczęciem gry. Wejście do rozgrywki oznacza akceptację regulaminu.\n"
        "Nieznajomość regulaminu nie zwalnia z jego przestrzegania.\n\n"
        "**ZASADY**\n"
        "• Za łamanie zasad grozi ban.\n"
        "• Administracja może ukarać gracza również za zachowanie, które nie zostało opisane w regulaminie.\n\n"
        "**OGÓLNE**\n"
        "• Zabrania się wykorzystywania błędów serwera. Brak zgłoszenia błędu jest traktowany jako jego używanie.\n"
        "• Zakaz korzystania z cheatów oraz niedozwolonych modyfikacji. Samo posiadanie traktowane jest jak używanie.\n"
        "• Zakazuje się posiadania więcej niż jednego konta.\n"
        "• Zabrania się utrudniania gry graczom i administracji.\n"
        "• Jeśli uważasz, że twój ban został nadany niesłusznie, możesz się odwołać na tickecie."
    ),
    "powitanie_tytul": "NOWA OSOBA NA SERWERZE!",
    "powitanie_tekst": (
        "👋 Witamy {mention}, miło cię widzieć!\n"
        "👤 Jesteś **{ilosc}** członkiem serwera.\n\n"
        "Miło cię widzieć na naszym serwerze. Sprawdź najważniejsze kanały i wskakuj do gry."
    ),
    "pozegnanie_tytul": "Ktoś nas opuścił...",
    "pozegnanie_tekst": "👋 **{nazwa}** opuścił serwer. Zostało nas **{ilosc}**.",
    "ticket_tytul": "Centrum Pomocy - Tworzenie Ticketa",
    "ticket_opis": (
        "Chcesz skontaktować się z administracją? Wybierz kategorię z menu poniżej, aby utworzyć ticket.\n\n"
        "**Zasady dotyczące ticketów**\n"
        "• Tworzenie niepotrzebnych lub niepoważnych ticketów jest zabronione.\n"
        "• Opisz sprawę krótko i konkretnie.\n"
        "• Nie podawaj haseł ani prywatnych danych."
    ),
    "ticket_kategorie": {
        "pomoc": {
            "etykieta": "🛠️ Pomoc ogólna",
            "pytania": [],
        },
        "rekrutacja": {
            "etykieta": "👥 Rekrutacja",
            "pytania": [
                {"tresc": "Na jaką range aspirujesz?", "styl": "short", "wymagane": True, "placeholder": "np. Helper / Moderator", "max_length": 100},
                {"tresc": "Ile masz lat?", "styl": "short", "wymagane": True, "placeholder": "np. 16", "max_length": 10},
                {"tresc": "Dlaczego mamy wybrać właśnie Ciebie?", "styl": "paragraph", "wymagane": True, "placeholder": "Napisz, co Cię wyróżnia.", "max_length": 1000},
                {"tresc": "Co wniesiesz do serwera?", "styl": "paragraph", "wymagane": True, "placeholder": "Opisz, jak chcesz pomóc w rozwoju serwera.", "max_length": 1000},
                {"tresc": "Doświadczenie w administracji", "styl": "paragraph", "wymagane": True, "placeholder": "Opisz swoje wcześniejsze doświadczenie.", "max_length": 1000},
            ],
        },
        "partnerstwo": {
            "etykieta": "🤝 Partnerstwo",
            "pytania": [
                {"tresc": "Link do Twojego Discorda", "styl": "short", "wymagane": True, "placeholder": "np. https://discord.gg/twoj-serwer", "max_length": 200},
                {"tresc": "Partnerstwo z pingiem czy bez?", "styl": "short", "wymagane": True, "placeholder": "np. z pingiem / bez pinga", "max_length": 50},
            ],
        },
        "zgloszenie": {
            "etykieta": "🚨 Zgłoś cheatera",
            "pytania": [
                {"tresc": "Nick cheatera", "styl": "short", "wymagane": True, "placeholder": "np. NickGracza", "max_length": 50},
                {"tresc": "Opisz sytuację", "styl": "paragraph", "wymagane": True, "placeholder": "Napisz, co dokładnie się wydarzyło.", "max_length": 1000},
                {"tresc": "Klip z dowodem", "styl": "paragraph", "wymagane": False, "placeholder": "Wklej link do klipu albo napisz, że wyślesz go w tickecie.", "max_length": 500},
            ],
        },
        "media": {
            "etykieta": "📸 Media",
            "pytania": [
                {"tresc": "Link do Twoich sociali", "styl": "paragraph", "wymagane": True, "placeholder": "YouTube / TikTok / Twitch / Instagram", "max_length": 700},
            ],
        },
        "odwolanie": {
            "etykieta": "❤️ Odwołanie od bana",
            "pytania": [
                {"tresc": "Nick gracza", "styl": "short", "wymagane": True, "placeholder": "np. Swequuu", "max_length": 50},
                {"tresc": "Dlaczego ban jest niesłuszny?", "styl": "paragraph", "wymagane": True, "placeholder": "Opisz dokładnie, dlaczego chcesz odwołać bana.", "max_length": 1000},
                {"tresc": "Screen z próby wejścia na serwer", "styl": "paragraph", "wymagane": True, "placeholder": "Wklej link do screena z próby wejścia na serwer.", "max_length": 500},
            ],
        },
        "inne": {
            "etykieta": "❓ Inne",
            "pytania": [
                {"tresc": "Czego dotyczy sprawa?", "styl": "paragraph", "wymagane": True, "placeholder": "Napisz krótko, w czym mamy pomóc.", "max_length": 1000},
            ],
        },
        "wsparcie": {
            "etykieta": "💰 Wsparcie serwera",
            "pytania": [],
        },
    },
    "footer": "IGRZYSKA FFA",
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
            return merged, True
        except Exception as e:
            print(f"Błąd wczytywania configu, używam domyślnego: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG)), False


def save_config():
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)


CONFIG, _config_existed = load_config()

# Jednorazowe "zasilenie" configu starymi zmiennymi środowiskowymi (tylko gdy
# config.json jeszcze nie istniał - potem wszystko trzyma się w JSON-ie).
if not _config_existed:
    if _SEED_WELCOME_CHANNEL_ID:
        CONFIG["channels"]["powitanie"] = _SEED_WELCOME_CHANNEL_ID
    if _SEED_GOODBYE_CHANNEL_ID:
        CONFIG["channels"]["pozegnanie"] = _SEED_GOODBYE_CHANNEL_ID
    if _SEED_TICKET_CATEGORY_ID:
        CONFIG["ticket_category_id"] = _SEED_TICKET_CATEGORY_ID
    if _SEED_STAFF_ROLE_ID:
        CONFIG["roles"]["staff"] = _SEED_STAFF_ROLE_ID
    if _SEED_VERIFY_ROLE_ID:
        CONFIG["roles"]["weryfikacja"] = _SEED_VERIFY_ROLE_ID
    save_config()

# Migracja starego formatu kategorii ticketów (gdzie wartość była samym tekstem)
# do nowego formatu (etykieta + lista pytań formularza).
_zmieniono_kategorie = False
for _klucz, _wartosc in CONFIG["ticket_kategorie"].items():
    if isinstance(_wartosc, str):
        CONFIG["ticket_kategorie"][_klucz] = {"etykieta": _wartosc, "pytania": []}
        _zmieniono_kategorie = True
if _zmieniono_kategorie:
    save_config()

# Migracja starego formatu harmonogramu Igrzysk (jedna godzina jako tekst,
# jedna data ostatniej wysyłki) do nowego formatu (lista godzin, lista wysyłek).
_zmieniono_igrzyska = False
_ig = CONFIG["igrzyska"]
if "godzina" in _ig:
    stara_godzina = _ig.pop("godzina")
    if not _ig.get("godziny"):
        _ig["godziny"] = [stara_godzina] if stara_godzina else ["18:00"]
    _zmieniono_igrzyska = True
if "ostatnio_wyslano_data" in _ig:
    _ig.pop("ostatnio_wyslano_data")
    _zmieniono_igrzyska = True
if "godziny" not in _ig or not _ig["godziny"]:
    _ig["godziny"] = ["18:00"]
    _zmieniono_igrzyska = True
if "ostatnio_wyslane" not in _ig:
    _ig["ostatnio_wyslane"] = []
    _zmieniono_igrzyska = True
if "typ_ping" not in _ig:
    _ig["typ_ping"] = "brak"
    _zmieniono_igrzyska = True
if "rola_ping_id" not in _ig:
    _ig["rola_ping_id"] = 0
    _zmieniono_igrzyska = True
if "typ_ping_start" not in _ig:
    _ig["typ_ping_start"] = "everyone"
    _zmieniono_igrzyska = True
if "rola_ping_start_id" not in _ig:
    _ig["rola_ping_start_id"] = 0
    _zmieniono_igrzyska = True
if _zmieniono_igrzyska:
    save_config()

# Migracja starych obrazków zapisanych jako linki (np. wygasające linki CDN Discorda
# albo stary placeholder) do nowego systemu lokalnych plików.
_zmieniono_obrazki = False
for _typ, _wartosc in list(CONFIG["images"].items()):
    if _wartosc and _wartosc.startswith("http"):
        try:
            import urllib.request
            _ext = os.path.splitext(_wartosc.split("?")[0])[1] or ".png"
            _sciezka = os.path.join(IMAGES_DIR, f"{_typ}{_ext}")
            urllib.request.urlretrieve(_wartosc, _sciezka)
            CONFIG["images"][_typ] = _sciezka
        except Exception as _e:
            print(f"Nie udało się zmigrować starego obrazka '{_typ}': {_e}")
            CONFIG["images"][_typ] = ""
        _zmieniono_obrazki = True
if _zmieniono_obrazki:
    save_config()


class SafeDict(dict):
    """Pozwala używać .format() bez wywalania się, gdy ktoś wpisze zły placeholder."""
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, **kwargs) -> str:
    return template.format_map(SafeDict(**kwargs))


def hex_to_color(value: str) -> discord.Color:
    """Zamienia string typu '#FF0000' / 'FF0000' na discord.Color. Rzuca ValueError gdy błędny format."""
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("Kolor musi być w formacie HEX, np. #FF0000")
    return discord.Color(int(value, 16))


def get_color(typ: str) -> discord.Color:
    try:
        return hex_to_color(CONFIG["colors"].get(typ, "#E74C3C"))
    except ValueError:
        return discord.Color.red()


def prepare_embed_image(embed: discord.Embed, typ: str, miniaturka: bool = False) -> Optional[discord.File]:
    """Jeśli admin ustawił obrazek dla danego typu (komendą .../obrazek), dołącza go
    do embeda jako świeży załącznik (attachment://...), zamiast linku - dzięki temu
    obrazek nigdy nie "wygasa". Zwraca discord.File do przekazania przy wysyłce/edycji
    (albo None, jeśli nic nie ustawiono)."""
    sciezka = CONFIG["images"].get(typ)
    if not sciezka or not os.path.exists(sciezka):
        return None
    nazwa_pliku = os.path.basename(sciezka)
    if miniaturka:
        embed.set_thumbnail(url=f"attachment://{nazwa_pliku}")
    else:
        embed.set_image(url=f"attachment://{nazwa_pliku}")
    return discord.File(sciezka, filename=nazwa_pliku)


# ========================
#   INICJALIZACJA BOTA
# ========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

ADMIN_ONLY = app_commands.checks.has_permissions(administrator=True)


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


def footer_icon(guild: discord.Guild):
    return guild.icon.url if guild and guild.icon else None


async def deny_no_admin(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Ta opcja (`Edytuj`) jest tylko dla administracji.", ephemeral=True
    )


async def send_or_edit_panel(target: discord.TextChannel, embed: discord.Embed, view: discord.ui.View, klucz: str, plik: Optional[discord.File] = None):
    """Wysyła panel na kanał, albo edytuje wcześniej wysłaną wiadomość jeśli taka istnieje na tym samym kanale.
    Dzięki temu zmiana kategorii/treści nie tworzy duplikatów paneli."""
    info = CONFIG["panel_messages"].setdefault(klucz, {"channel_id": 0, "message_id": 0})
    if info["channel_id"] == target.id and info["message_id"]:
        try:
            msg = await target.fetch_message(info["message_id"])
            if plik:
                await msg.edit(embed=embed, view=view, attachments=[plik])
            else:
                await msg.edit(embed=embed, view=view)
            return msg, True  # zedytowano istniejącą
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass  # wiadomość usunięta/niedostępna - wyślemy nową poniżej

    msg = await target.send(embed=embed, view=view, file=plik)
    info["channel_id"] = target.id
    info["message_id"] = msg.id
    save_config()
    return msg, False  # wysłano nową



@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(VerifyView())
    bot.add_view(PropozycjaView())

    guild = discord.Object(id=TEST_GUILD_ID)

    # Najpierw kopiujemy aktualne komendy do serwera testowego...
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)

    # ...dopiero teraz czyścimy stare, globalnie zarejestrowane komendy (np. z wcześniejszych
    # wersji bota), żeby nie pokazywały się jako duplikaty. To nie usuwa komend z serwera testowego,
    # bo te zostały już wysłane linijkę wyżej.
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()

    if not sprawdzaj_harmonogram_igrzysk.is_running():
        sprawdzaj_harmonogram_igrzysk.start()

    print(f"Zalogowano jako {bot.user} - komendy zsynchronizowane.")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "Nie masz uprawnień administratora, żeby użyć tej komendy."
    elif isinstance(error, app_commands.CommandInvokeError):
        msg = f"Wystąpił błąd: {error.original}"
    else:
        msg = f"Wystąpił błąd: {error}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ========================
#   POWITANIA / POŻEGNANIA
# ========================

@bot.event
async def on_member_join(member: discord.Member):
    channel_id = CONFIG["channels"].get("powitanie")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    text = render(CONFIG["powitanie_tekst"], mention=member.mention, nazwa=member.name, ilosc=member.guild.member_count)
    embed = discord.Embed(
        title=CONFIG["powitanie_tytul"],
        description=text,
        color=get_color("powitanie"),
        timestamp=datetime.datetime.now()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    plik = prepare_embed_image(embed, "powitanie")
    embed.set_footer(text=CONFIG["footer"])
    await channel.send(content=member.mention, embed=embed, file=plik)


@bot.event
async def on_member_remove(member: discord.Member):
    channel_id = CONFIG["channels"].get("pozegnanie")
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    text = render(CONFIG["pozegnanie_tekst"], mention=member.mention, nazwa=member.name, ilosc=member.guild.member_count)
    embed = discord.Embed(
        title=CONFIG["pozegnanie_tytul"],
        description=text,
        color=get_color("pozegnanie"),
        timestamp=datetime.datetime.now()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    plik = prepare_embed_image(embed, "pozegnanie")
    embed.set_footer(text=CONFIG["footer"])
    await channel.send(embed=embed, file=plik)


# ========================
#   SYSTEM PROPOZYCJI
#   Każda wiadomość na wyznaczonym kanale zamienia się w propozycję z głosowaniem.
# ========================

def _wyniki_glosowania_tekst(message_id: int) -> str:
    glosy = CONFIG["propozycje_glosy"].get(str(message_id), {"tak": [], "nie": []})
    tak, nie = len(glosy["tak"]), len(glosy["nie"])
    total = tak + nie
    proc_tak = round(tak / total * 100) if total else 0
    proc_nie = round(nie / total * 100) if total else 0
    return f"✅ {tak} ({proc_tak}%)   ❌ {nie} ({proc_nie}%)"


class PropozycjaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _glosuj(self, interaction: discord.Interaction, wybor: str):
        mid = str(interaction.message.id)
        glosy = CONFIG["propozycje_glosy"].setdefault(mid, {"tak": [], "nie": []})
        uid = interaction.user.id
        for lista in glosy.values():
            if uid in lista:
                lista.remove(uid)
        glosy[wybor].append(uid)
        save_config()

        embed = interaction.message.embeds[0]
        embed.set_field_at(2, name="📊 Wyniki", value=_wyniki_glosowania_tekst(interaction.message.id), inline=False)
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(label="TAK", emoji="✅", style=discord.ButtonStyle.success, custom_id="propozycja_tak")
    async def tak(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._glosuj(interaction, "tak")

    @discord.ui.button(label="NIE", emoji="❌", style=discord.ButtonStyle.danger, custom_id="propozycja_nie")
    async def nie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._glosuj(interaction, "nie")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    kanal_id = CONFIG["channels"].get("propozycje")
    if kanal_id and message.channel.id == kanal_id and message.content.strip():
        tresc = message.content
        autor = message.author
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        embed = discord.Embed(title=f"{message.guild.name} x Propozycja", color=get_color("akcent"))
        embed.add_field(name="👤 Od", value=autor.mention, inline=False)
        embed.add_field(name="💡 Propozycja", value=tresc[:1024], inline=False)
        embed.add_field(name="📊 Wyniki", value="✅ 0 (0%)   ❌ 0 (0%)", inline=False)
        plik = prepare_embed_image(embed, "propozycja", miniaturka=True)
        embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(message.guild))

        wiadomosc = await message.channel.send(embed=embed, view=PropozycjaView(), file=plik)
        try:
            await wiadomosc.create_thread(name=f"Propozycja | {autor.name}"[:100], auto_archive_duration=1440)
        except discord.HTTPException:
            pass

    await bot.process_commands(message)


# ========================
#   IGRZYSKA ŚMIERCI (RCON + harmonogram + reakcje)
# ========================

async def rcon_wykonaj(komenda: str) -> tuple[bool, str]:
    """Wysyła komendę do serwera Minecraft przez RCON. Zwraca (sukces, wynik_albo_blad).
    mcrcon jest biblioteką synchroniczną, więc wykonujemy ją w osobnym wątku (asyncio.to_thread),
    żeby nie zablokować bota na czas połączenia."""
    cfg = CONFIG["igrzyska"]
    if MCRcon is None:
        return False, "Biblioteka 'mcrcon' nie jest zainstalowana na serwerze bota (pip install mcrcon)."
    if not cfg["rcon_host"] or not cfg["rcon_haslo"]:
        return False, "RCON nie jest skonfigurowany - ustaw host/port/hasło w `/konfiguracja igrzyska`."

    def _wykonaj():
        with MCRcon(cfg["rcon_host"], cfg["rcon_haslo"], port=cfg["rcon_port"]) as mcr:
            mcr.socket.settimeout(5)
            return mcr.command(komenda)

    try:
        wynik = await asyncio.to_thread(_wykonaj)
        return True, wynik
    except Exception as e:
        return False, str(e)


def zbuduj_ping(cfg: dict, klucz_typu: str, klucz_roli: str):
    """Zwraca (content, allowed_mentions) do wysyłki wiadomości, zależnie od trybu pingu w configu.

    klucz_typu / klucz_roli - nazwy pól w cfg["igrzyska"], np. "typ_ping"/"rola_ping_id"
    (zapowiedź) albo "typ_ping_start"/"rola_ping_start_id" (start lobby).
    """
    typ = cfg.get(klucz_typu, "brak")
    if typ == "everyone":
        return "@everyone", discord.AllowedMentions(everyone=True, roles=False, users=False)
    if typ == "rola" and cfg.get(klucz_roli):
        return f"<@&{cfg[klucz_roli]}>", discord.AllowedMentions(everyone=False, roles=True, users=False)
    return None, discord.AllowedMentions.none()


def zbuduj_ping_zapowiedzi(cfg: dict):
    """Zwraca (content, allowed_mentions) do wysyłki zapowiedzi, zależnie od trybu pingu w configu."""
    return zbuduj_ping(cfg, "typ_ping", "rola_ping_id")


def zbuduj_ping_startu(cfg: dict):
    """Zwraca (content, allowed_mentions) do wysyłki ogłoszenia startu, zależnie od trybu pingu w configu."""
    return zbuduj_ping(cfg, "typ_ping_start", "rola_ping_start_id")


async def wyslij_zapowiedz_igrzysk(kanal: discord.TextChannel):
    """Wysyła wiadomość zapowiadającą Igrzyska i dodaje pod nią reakcję do zbierania zapisów."""
    cfg = CONFIG["igrzyska"]
    tresc = render(cfg["wiadomosc_zapowiedz_tresc"], emoji=cfg["emoji_reakcja"], wymagane=cfg["wymagane_reakcje"])
    embed = discord.Embed(title=cfg["wiadomosc_zapowiedz_tytul"], description=tresc, color=get_color("akcent"))
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(kanal.guild))
    ping_tresc, ping_allowed = zbuduj_ping_zapowiedzi(cfg)
    wiadomosc = await kanal.send(content=ping_tresc, embed=embed, allowed_mentions=ping_allowed)
    try:
        await wiadomosc.add_reaction(cfg["emoji_reakcja"])
    except discord.HTTPException:
        pass
    cfg["aktualna_wiadomosc_id"] = wiadomosc.id
    cfg["aktualny_kanal_id"] = kanal.id
    cfg["w_trakcie"] = False
    save_config()


async def rozpocznij_igrzyska(guild: discord.Guild):
    """Wysyła ogłoszenie startu (ping wg konfiguracji), odpala lobby przez RCON i planuje jego zamknięcie za 10 minut."""
    cfg = CONFIG["igrzyska"]
    kanal_ogl = guild.get_channel(cfg["kanal_ogloszenia"]) or guild.get_channel(cfg["kanal_zapowiedzi"])

    if kanal_ogl:
        embed = discord.Embed(title="🏹 Igrzyska Śmierci - START!", description=cfg["wiadomosc_start_tresc"], color=get_color("akcent"))
        embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(guild))
        ping_tresc, ping_allowed = zbuduj_ping_startu(cfg)
        await kanal_ogl.send(content=ping_tresc, embed=embed, allowed_mentions=ping_allowed)

    sukces, wynik = await rcon_wykonaj(cfg["komenda_start"])
    if not sukces and kanal_ogl:
        await kanal_ogl.send(f"⚠️ Nie udało się połączyć z serwerem przez RCON (start lobby): {wynik}")

    asyncio.create_task(zamknij_lobby_po_czasie(guild))


async def zamknij_lobby_po_czasie(guild: discord.Guild):
    """Czeka 10 minut od otwarcia lobby, a potem zamyka je przez RCON i informuje na Discordzie."""
    await asyncio.sleep(600)
    cfg = CONFIG["igrzyska"]

    sukces, wynik = await rcon_wykonaj(cfg["komenda_zamknij"])
    kanal_ogl = guild.get_channel(cfg["kanal_ogloszenia"]) or guild.get_channel(cfg["kanal_zapowiedzi"])
    if kanal_ogl:
        embed = discord.Embed(description=cfg["wiadomosc_zamkniecie_tresc"], color=get_color("akcent"))
        embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(guild))
        await kanal_ogl.send(embed=embed)
        if not sukces:
            await kanal_ogl.send(f"⚠️ Nie udało się zamknąć lobby przez RCON: {wynik}")

    cfg["w_trakcie"] = False
    cfg["aktualna_wiadomosc_id"] = 0
    save_config()


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    cfg = CONFIG["igrzyska"]
    if bot.user and payload.user_id == bot.user.id:
        return
    if not cfg.get("aktualna_wiadomosc_id") or payload.message_id != cfg["aktualna_wiadomosc_id"]:
        return
    if str(payload.emoji) != cfg.get("emoji_reakcja"):
        return
    if cfg.get("w_trakcie"):
        return  # lobby już wystartowało - nie liczymy dalej

    kanal = bot.get_channel(payload.channel_id)
    if kanal is None:
        return
    try:
        wiadomosc = await kanal.fetch_message(payload.message_id)
    except discord.HTTPException:
        return

    for reakcja in wiadomosc.reactions:
        if str(reakcja.emoji) == cfg.get("emoji_reakcja"):
            liczba = reakcja.count - 1  # -1, bo bot sam dodał tę reakcję na starcie
            if liczba >= cfg.get("wymagane_reakcje", 15):
                cfg["w_trakcie"] = True
                save_config()
                await rozpocznij_igrzyska(wiadomosc.guild)
            break


@tasks.loop(seconds=30)
async def sprawdzaj_harmonogram_igrzysk():
    cfg = CONFIG["igrzyska"]
    if not cfg.get("harmonogram_aktywny") or not cfg.get("kanal_zapowiedzi"):
        return

    # Realny czas polski (Europe/Warsaw) - niezależnie od strefy czasowej serwera,
    # na którym stoi bot, więc godziny w panelu odpowiadają rzeczywistej godzinie.
    teraz = datetime.datetime.now(STREFA_CZASOWA)
    aktualna_godzina = teraz.strftime("%H:%M")
    godziny = cfg.get("godziny") or []
    if aktualna_godzina not in godziny:
        return

    znacznik = teraz.strftime("%Y-%m-%d %H:%M")
    wyslane = cfg.setdefault("ostatnio_wyslane", [])
    if znacznik in wyslane:
        return  # o tej konkretnej godzinie dzisiaj już wysłano, nie duplikujemy

    kanal = bot.get_channel(cfg["kanal_zapowiedzi"])
    if kanal:
        await wyslij_zapowiedz_igrzysk(kanal)

    wyslane.append(znacznik)
    # sprzątamy wpisy sprzed dzisiaj, żeby lista nie rosła w nieskończoność
    dzisiaj = teraz.strftime("%Y-%m-%d")
    cfg["ostatnio_wyslane"] = [w for w in wyslane if w.startswith(dzisiaj)]
    save_config()


@sprawdzaj_harmonogram_igrzysk.before_loop
async def przed_harmonogramem_igrzysk():
    await bot.wait_until_ready()


# ========================
#   REGULAMIN
# ========================

@bot.tree.command(name="regulamin", description="Wyświetla lub edytuje regulamin serwera")
@app_commands.describe(akcja="Co chcesz zrobić", kanal="Gdzie wysłać regulamin (domyślnie ten kanał)")
@app_commands.choices(akcja=[
    app_commands.Choice(name="📜 Wyświetl", value="wyswietl"),
    app_commands.Choice(name="✏️ Edytuj", value="edytuj"),
])
async def regulamin(
    interaction: discord.Interaction,
    akcja: Optional[app_commands.Choice[str]] = None,
    kanal: Optional[discord.TextChannel] = None,
):
    wartosc = akcja.value if akcja else "wyswietl"
    if wartosc == "edytuj":
        if not is_admin(interaction):
            await deny_no_admin(interaction)
            return
        await interaction.response.send_modal(RegulaminModal())
        return

    embed = discord.Embed(title="📜 Regulamin FFA", description=CONFIG["regulamin"], color=get_color("akcent"))
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    if kanal and kanal.id != interaction.channel.id:
        await kanal.send(embed=embed)
        await interaction.response.send_message(f"Regulamin wysłany na {kanal.mention} ✅", ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed)


# ========================
#   MODALE (edycja tekstów)
# ========================

@bot.tree.command(name="pomoc", description="Pokazuje listę wszystkich dostępnych komend")
async def pomoc(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Pomoc - lista komend", color=get_color("akcent"))
    embed.add_field(
        name="👤 Dla każdego",
        value=(
            "`/regulamin` - wyświetla regulamin serwera\n"
            "`/pomoc` - ta lista\n\n"
            "🎫 Ticket otwierasz wybierając kategorię z menu na kanale ticketów.\n"
            "✅ Weryfikujesz się klikając przycisk na kanale weryfikacji."
        ),
        inline=False,
    )
    if is_admin(interaction):
        embed.add_field(
            name="✉️ Wiadomości bota (podgląd / edycja / kanał)",
            value=(
                "`/regulamin` - `Wyświetl` / `Edytuj`\n"
                "`/powitanie` - `Podgląd` / `Edytuj treść` / `Ustaw kanał`\n"
                "`/pozegnanie` - `Podgląd` / `Edytuj treść` / `Ustaw kanał`\n"
                "`/ticket_wiadomosc` - `Podgląd` / `Edytuj treść`\n"
                "`/ticket_panel` - `Wyślij panel` / `Edytuj treść panelu`\n"
                "`/panel_weryfikacji` - `Wyślij panel` / `Edytuj treść panelu`\n"
                "`/mow` - wysyła dowolną wiadomość przez bota na wybrany kanał\n"
                "`/embed` - wysyła wiadomość w ramce (embed) przez bota"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛠️ Konfiguracja (`/konfiguracja ...`)",
            value=(
                "`kategorie` - panel do zarządzania kategoriami ticketów i ich formularzami (lista + przyciski)\n"
                "`igrzyska` - panel Igrzysk Śmierci (kanały, treści, RCON, emoji, harmonogram)\n"
                "`kolor` - kolor bocznego paska embedów\n"
                "`rola` - rola staffu / weryfikacji\n"
                "`kategoria_ticketow` - kategoria kanałów pod nowe tickety\n"
                "`propozycje` - kanał, na którym wiadomości zamieniają się w propozycje z głosowaniem\n"
                "`obrazek` - banery powitania / pożegnania / ticketów / weryfikacji / propozycji\n"
                "`podglad` - pokazuje całą aktualną konfigurację"
            ),
            inline=False,
        )
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="mow", description="[ADMIN] Wysyła wiadomość przez bota na wskazany kanał")
@app_commands.describe(kanal="Kanał docelowy")
@ADMIN_ONLY
async def mow(interaction: discord.Interaction, kanal: discord.TextChannel):
    await interaction.response.send_modal(MowModal(kanal))


class MowModal(discord.ui.Modal, title="Wyślij wiadomość przez bota"):
    def __init__(self, kanal: discord.TextChannel):
        super().__init__()
        self.kanal = kanal
        self.tresc = discord.ui.TextInput(label="Treść wiadomości", style=discord.TextStyle.paragraph, max_length=2000)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        await self.kanal.send(str(self.tresc.value))
        await interaction.response.send_message(f"Wysłano na {self.kanal.mention} ✅", ephemeral=True)


@bot.tree.command(name="embed", description="[ADMIN] Wysyła wiadomość w ramce (embed) przez bota")
@app_commands.describe(kanal="Kanał docelowy")
@ADMIN_ONLY
async def embed_cmd(interaction: discord.Interaction, kanal: discord.TextChannel):
    await interaction.response.send_modal(EmbedModal(kanal))


class EmbedModal(discord.ui.Modal, title="Wyślij embed przez bota"):
    def __init__(self, kanal: discord.TextChannel):
        super().__init__()
        self.kanal = kanal
        self.tytul = discord.ui.TextInput(label="Tytuł", max_length=256)
        self.tresc = discord.ui.TextInput(label="Treść", style=discord.TextStyle.paragraph, max_length=4000)
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=str(self.tytul.value), description=str(self.tresc.value), color=get_color("akcent"))
        embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
        await self.kanal.send(embed=embed)
        await interaction.response.send_message(f"Wysłano embed na {self.kanal.mention} ✅", ephemeral=True)


class RegulaminModal(discord.ui.Modal, title="Edytuj regulamin"):
    def __init__(self):
        super().__init__()
        self.tresc = discord.ui.TextInput(
            label="Treść regulaminu",
            style=discord.TextStyle.paragraph,
            default=CONFIG["regulamin"][:4000],
            max_length=4000,
            required=True,
        )
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["regulamin"] = str(self.tresc.value)
        save_config()
        await interaction.response.send_message("Regulamin zaktualizowany ✅", ephemeral=True)


class PowitanieModal(discord.ui.Modal, title="Edytuj wiadomość powitalną"):
    def __init__(self):
        super().__init__()
        self.tytul = discord.ui.TextInput(label="Tytuł", default=CONFIG["powitanie_tytul"], max_length=256, required=True)
        self.tresc = discord.ui.TextInput(
            label="Treść (dostępne: {mention} {nazwa} {ilosc})",
            style=discord.TextStyle.paragraph,
            default=CONFIG["powitanie_tekst"][:4000],
            max_length=4000,
            required=True,
        )
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["powitanie_tytul"] = str(self.tytul.value)
        CONFIG["powitanie_tekst"] = str(self.tresc.value)
        save_config()
        await interaction.response.send_message("Wiadomość powitalna zaktualizowana ✅", ephemeral=True)


class PozegnanieModal(discord.ui.Modal, title="Edytuj wiadomość pożegnalną"):
    def __init__(self):
        super().__init__()
        self.tytul = discord.ui.TextInput(label="Tytuł", default=CONFIG["pozegnanie_tytul"], max_length=256, required=True)
        self.tresc = discord.ui.TextInput(
            label="Treść (dostępne: {mention} {nazwa} {ilosc})",
            style=discord.TextStyle.paragraph,
            default=CONFIG["pozegnanie_tekst"][:4000],
            max_length=4000,
            required=True,
        )
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["pozegnanie_tytul"] = str(self.tytul.value)
        CONFIG["pozegnanie_tekst"] = str(self.tresc.value)
        save_config()
        await interaction.response.send_message("Wiadomość pożegnalna zaktualizowana ✅", ephemeral=True)


class TicketOpisModal(discord.ui.Modal, title="Edytuj panel ticketów"):
    def __init__(self):
        super().__init__()
        self.tytul = discord.ui.TextInput(label="Tytuł", default=CONFIG["ticket_tytul"], max_length=256, required=True)
        self.tresc = discord.ui.TextInput(
            label="Opis panelu", style=discord.TextStyle.paragraph,
            default=CONFIG["ticket_opis"][:4000], max_length=4000, required=True
        )
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["ticket_tytul"] = str(self.tytul.value)
        CONFIG["ticket_opis"] = str(self.tresc.value)
        save_config()
        await interaction.response.send_message(
            "Zapisano ✅ (jeśli panel już wisi na kanale, wyślij go ponownie /ticket_panel, żeby zaktualizować widok).",
            ephemeral=True
        )


class TicketWiadomoscModal(discord.ui.Modal, title="Edytuj wiadomość wewnątrz ticketu"):
    def __init__(self):
        super().__init__()
        self.tresc = discord.ui.TextInput(
            label="Treść powitalna ({mention} {nazwa} {rola})",
            style=discord.TextStyle.paragraph,
            default=CONFIG["ticket_wiadomosc_tresc"][:4000],
            max_length=4000,
            required=True,
        )
        self.zasady = discord.ui.TextInput(
            label="Zasady/info ({mention} {nazwa} {rola}) - puste = brak",
            style=discord.TextStyle.paragraph,
            default=CONFIG.get("ticket_zasady_tekst", "")[:4000],
            max_length=4000,
            required=False,
        )
        self.add_item(self.tresc)
        self.add_item(self.zasady)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["ticket_wiadomosc_tresc"] = str(self.tresc.value)
        CONFIG["ticket_zasady_tekst"] = str(self.zasady.value)
        save_config()
        await interaction.response.send_message("Zapisano ✅ (dotyczy nowo otwieranych ticketów).", ephemeral=True)


class WeryfikacjaModal(discord.ui.Modal, title="Edytuj panel weryfikacji"):
    def __init__(self):
        super().__init__()
        self.tytul = discord.ui.TextInput(label="Tytuł", default=CONFIG["weryfikacja_tytul"], max_length=256, required=True)
        self.tresc = discord.ui.TextInput(
            label="Opis panelu", style=discord.TextStyle.paragraph,
            default=CONFIG["weryfikacja_opis"][:4000], max_length=4000, required=True
        )
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["weryfikacja_tytul"] = str(self.tytul.value)
        CONFIG["weryfikacja_opis"] = str(self.tresc.value)
        save_config()
        await interaction.response.send_message(
            "Zapisano ✅ (jeśli panel już wisi na kanale, wyślij go ponownie, żeby zaktualizować widok).",
            ephemeral=True
        )


# ========================
#   POWITANIE / POŻEGNANIE / WIADOMOŚĆ TICKETU
#   (podgląd, edycja treści, wybór kanału - wszystko w jednej komendzie)
# ========================

@bot.tree.command(name="powitanie", description="Podgląd, edycja lub kanał wiadomości powitalnej")
@app_commands.describe(akcja="Co chcesz zrobić", kanal="Kanał do ustawienia (tylko dla 'Ustaw kanał')")
@app_commands.choices(akcja=[
    app_commands.Choice(name="👀 Podgląd", value="podglad"),
    app_commands.Choice(name="✏️ Edytuj treść", value="edytuj"),
    app_commands.Choice(name="📌 Ustaw kanał", value="kanal"),
])
@ADMIN_ONLY
async def powitanie(
    interaction: discord.Interaction,
    akcja: Optional[app_commands.Choice[str]] = None,
    kanal: Optional[discord.TextChannel] = None,
):
    wartosc = akcja.value if akcja else "podglad"

    if wartosc == "edytuj":
        await interaction.response.send_modal(PowitanieModal())
        return

    if wartosc == "kanal":
        if kanal is None:
            await interaction.response.send_message("Podaj parametr `kanal`, żeby ustawić nowy kanał powitań.", ephemeral=True)
            return
        CONFIG["channels"]["powitanie"] = kanal.id
        save_config()
        await interaction.response.send_message(f"Powitania będą wysyłane na {kanal.mention} ✅", ephemeral=True)
        return

    text = render(CONFIG["powitanie_tekst"], mention=interaction.user.mention, nazwa=interaction.user.name, ilosc=interaction.guild.member_count)
    embed = discord.Embed(title=CONFIG["powitanie_tytul"], description=text, color=get_color("powitanie"), timestamp=datetime.datetime.now())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    plik = prepare_embed_image(embed, "powitanie")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    aktualny_kanal = interaction.guild.get_channel(CONFIG["channels"]["powitanie"])
    info = f"\n\n📌 Aktualny kanał powitań: {aktualny_kanal.mention if aktualny_kanal else '*nie ustawiono*'}"
    await interaction.response.send_message(content="**Podgląd wiadomości powitalnej:**" + info, embed=embed, file=plik, ephemeral=True)


@bot.tree.command(name="pozegnanie", description="Podgląd, edycja lub kanał wiadomości pożegnalnej")
@app_commands.describe(akcja="Co chcesz zrobić", kanal="Kanał do ustawienia (tylko dla 'Ustaw kanał')")
@app_commands.choices(akcja=[
    app_commands.Choice(name="👀 Podgląd", value="podglad"),
    app_commands.Choice(name="✏️ Edytuj treść", value="edytuj"),
    app_commands.Choice(name="📌 Ustaw kanał", value="kanal"),
])
@ADMIN_ONLY
async def pozegnanie(
    interaction: discord.Interaction,
    akcja: Optional[app_commands.Choice[str]] = None,
    kanal: Optional[discord.TextChannel] = None,
):
    wartosc = akcja.value if akcja else "podglad"

    if wartosc == "edytuj":
        await interaction.response.send_modal(PozegnanieModal())
        return

    if wartosc == "kanal":
        if kanal is None:
            await interaction.response.send_message("Podaj parametr `kanal`, żeby ustawić nowy kanał pożegnań.", ephemeral=True)
            return
        CONFIG["channels"]["pozegnanie"] = kanal.id
        save_config()
        await interaction.response.send_message(f"Pożegnania będą wysyłane na {kanal.mention} ✅", ephemeral=True)
        return

    text = render(CONFIG["pozegnanie_tekst"], mention=interaction.user.mention, nazwa=interaction.user.name, ilosc=interaction.guild.member_count)
    embed = discord.Embed(title=CONFIG["pozegnanie_tytul"], description=text, color=get_color("pozegnanie"), timestamp=datetime.datetime.now())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    plik = prepare_embed_image(embed, "pozegnanie")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    aktualny_kanal = interaction.guild.get_channel(CONFIG["channels"]["pozegnanie"])
    info = f"\n\n📌 Aktualny kanał pożegnań: {aktualny_kanal.mention if aktualny_kanal else '*nie ustawiono*'}"
    await interaction.response.send_message(content="**Podgląd wiadomości pożegnalnej:**" + info, embed=embed, file=plik, ephemeral=True)


@bot.tree.command(name="ticket_wiadomosc", description="Podgląd lub edycja wiadomości wewnątrz nowo otwartego ticketu")
@app_commands.describe(akcja="Co chcesz zrobić")
@app_commands.choices(akcja=[
    app_commands.Choice(name="👀 Podgląd", value="podglad"),
    app_commands.Choice(name="✏️ Edytuj treść", value="edytuj"),
])
@ADMIN_ONLY
async def ticket_wiadomosc(interaction: discord.Interaction, akcja: Optional[app_commands.Choice[str]] = None):
    wartosc = akcja.value if akcja else "podglad"

    if wartosc == "edytuj":
        await interaction.response.send_modal(TicketWiadomoscModal())
        return

    staff_role_id = CONFIG["roles"].get("staff")
    staff_role = interaction.guild.get_role(staff_role_id) if staff_role_id else None
    rola_tekst = staff_role.mention if staff_role else "administracji"

    opis = render(CONFIG["ticket_wiadomosc_tresc"], mention=interaction.user.mention, nazwa=interaction.user.name, rola=rola_tekst)
    embed = discord.Embed(title="Ticket: (przykład)", description=opis, color=get_color("akcent"))
    zasady = render(CONFIG.get("ticket_zasady_tekst", ""), mention=interaction.user.mention, nazwa=interaction.user.name, rola=rola_tekst)
    if zasady.strip():
        embed.add_field(name="📌 Zasady", value=zasady, inline=False)
    plik = prepare_embed_image(embed, "ticket_wiadomosc")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    await interaction.response.send_message(content="**Podgląd wiadomości wewnątrz ticketu:**", embed=embed, file=plik, ephemeral=True)


# ========================
#   SYSTEM TICKETÓW
# ========================

async def create_ticket_channel(interaction: discord.Interaction, klucz: str, etykieta: str, odpowiedzi: Optional[dict] = None):
    """Tworzy kanał ticketu. Jeśli podano odpowiedzi (z formularza), pokazuje je jako pola embeda.
    Jeśli nie - używa ogólnej wiadomości (ticket_wiadomosc_tresc)."""
    guild = interaction.guild
    category = guild.get_channel(CONFIG["ticket_category_id"])

    existing = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name}".lower())
    if existing:
        await interaction.response.send_message(f"Masz już otwarty ticket: {existing.mention}", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    staff_role_id = CONFIG["roles"].get("staff")
    staff_role = guild.get_role(staff_role_id) if staff_role_id else None
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    channel = await guild.create_text_channel(
        name=f"ticket-{interaction.user.name}",
        category=category,
        overwrites=overwrites,
        topic=f"Ticket ({etykieta}) - {interaction.user.id}"
    )

    rola_tekst = staff_role.mention if staff_role else "administracji"
    embed = discord.Embed(title=f"Ticket: {etykieta}", color=get_color("akcent"))
    opis = render(CONFIG["ticket_wiadomosc_tresc"], mention=interaction.user.mention, nazwa=interaction.user.name, rola=rola_tekst)
    embed.description = opis
    if odpowiedzi:
        for pytanie, odp in odpowiedzi.items():
            embed.add_field(name=pytanie[:256], value=(odp[:1024] if odp else "*brak odpowiedzi*"), inline=False)
    zasady = render(CONFIG.get("ticket_zasady_tekst", ""), mention=interaction.user.mention, nazwa=interaction.user.name, rola=rola_tekst)
    if zasady.strip():
        embed.add_field(name="📌 Zasady", value=zasady, inline=False)
    plik = prepare_embed_image(embed, "ticket_wiadomosc")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(guild))

    # Pingujemy twórcę ticketu i skonfigurowaną rangę staffu (bez @everyone / @here).
    tresc_pingow = interaction.user.mention + (f" {staff_role.mention}" if staff_role else "")
    allowed = discord.AllowedMentions(everyone=False, roles=True, users=True)
    await channel.send(content=tresc_pingow, embed=embed, view=CloseTicketView(), file=plik, allowed_mentions=allowed)

    if interaction.response.is_done():
        await interaction.followup.send(f"Ticket utworzony: {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Ticket utworzony: {channel.mention}", ephemeral=True)


class DynamicTicketModal(discord.ui.Modal):
    """Modal budowany dynamicznie na podstawie pytań skonfigurowanych dla danej kategorii."""
    def __init__(self, klucz: str, etykieta: str, pytania: list):
        super().__init__(title=f"Ticket - {etykieta}"[:45])
        self.klucz = klucz
        self.etykieta = etykieta
        self.pola = []
        for pytanie in pytania[:5]:
            pole = discord.ui.TextInput(
                label=pytanie["tresc"][:45],
                style=discord.TextStyle.paragraph if pytanie.get("styl") == "paragraph" else discord.TextStyle.short,
                placeholder=(pytanie.get("placeholder") or None),
                required=pytanie.get("wymagane", True),
                max_length=pytanie.get("max_length", 1000 if pytanie.get("styl") == "paragraph" else 100),
            )
            self.add_item(pole)
            self.pola.append((pytanie["tresc"], pole))

    async def on_submit(self, interaction: discord.Interaction):
        odpowiedzi = {tresc: str(pole.value) for tresc, pole in self.pola}
        await create_ticket_channel(interaction, self.klucz, self.etykieta, odpowiedzi)


class TicketDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=dane["etykieta"], value=key)
            for key, dane in CONFIG["ticket_kategorie"].items()
        ] or [discord.SelectOption(label="Brak kategorii - dodaj je komendą /konfiguracja kategoria dodaj", value="brak")]
        super().__init__(placeholder="Wybierz kategorię...", options=options, custom_id="ticket_dropdown")

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "brak":
            await interaction.response.send_message("Administracja jeszcze nie skonfigurowała kategorii.", ephemeral=True)
            return

        dane = CONFIG["ticket_kategorie"].get(self.values[0])
        if dane is None:
            await interaction.response.send_message("Ta kategoria już nie istnieje. Odśwież panel komendą `/ticket_panel`.", ephemeral=True)
            return

        etykieta = dane["etykieta"]
        pytania = dane.get("pytania", [])

        if pytania:
            await interaction.response.send_modal(DynamicTicketModal(self.values[0], etykieta, pytania))
        else:
            await create_ticket_channel(interaction, self.values[0], etykieta)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketDropdown())


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Zamknij ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Zamykanie ticketu...")
        await interaction.channel.delete()


@bot.tree.command(name="ticket_panel", description="Wysyła lub edytuje panel tworzenia ticketów")
@app_commands.describe(akcja="Co chcesz zrobić", kanal="Gdzie wysłać panel (domyślnie ten kanał)")
@app_commands.choices(akcja=[
    app_commands.Choice(name="📨 Wyślij panel", value="wyslij"),
    app_commands.Choice(name="✏️ Edytuj treść panelu", value="edytuj"),
])
@ADMIN_ONLY
async def ticket_panel(
    interaction: discord.Interaction,
    akcja: Optional[app_commands.Choice[str]] = None,
    kanal: Optional[discord.TextChannel] = None,
):
    wartosc = akcja.value if akcja else "wyslij"
    if wartosc == "edytuj":
        await interaction.response.send_modal(TicketOpisModal())
        return

    target = kanal or interaction.channel
    embed = discord.Embed(title=CONFIG["ticket_tytul"], description=CONFIG["ticket_opis"], color=get_color("akcent"))
    plik = prepare_embed_image(embed, "ticket")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    msg, edytowano = await send_or_edit_panel(target, embed, TicketView(), "ticket", plik)
    CONFIG["channels"]["ticket_panel"] = target.id
    save_config()
    akcja_tekst = "zaktualizowany (edytowano istniejącą wiadomość)" if edytowano else "wysłany jako nowa wiadomość"
    await interaction.response.send_message(f"Panel {akcja_tekst} na {target.mention} ✅", ephemeral=True)


# ========================
#   WERYFIKACJA
# ========================

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Zweryfikuj się", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        role_id = CONFIG["roles"].get("weryfikacja")
        if not role_id:
            await interaction.response.send_message("Administracja nie skonfigurowała jeszcze roli weryfikacji.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("Nie znaleziono roli weryfikacji na serwerze.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("Jesteś już zweryfikowany/a ✅", ephemeral=True)
            return
        await interaction.user.add_roles(role)
        await interaction.response.send_message("Zweryfikowano! Miłego pobytu na serwerze 🎉", ephemeral=True)


@bot.tree.command(name="panel_weryfikacji", description="Wysyła lub edytuje panel weryfikacji")
@app_commands.describe(akcja="Co chcesz zrobić", kanal="Gdzie wysłać panel (domyślnie ten kanał)")
@app_commands.choices(akcja=[
    app_commands.Choice(name="📨 Wyślij panel", value="wyslij"),
    app_commands.Choice(name="✏️ Edytuj treść panelu", value="edytuj"),
])
@ADMIN_ONLY
async def panel_weryfikacji(
    interaction: discord.Interaction,
    akcja: Optional[app_commands.Choice[str]] = None,
    kanal: Optional[discord.TextChannel] = None,
):
    wartosc = akcja.value if akcja else "wyslij"
    if wartosc == "edytuj":
        await interaction.response.send_modal(WeryfikacjaModal())
        return

    target = kanal or interaction.channel
    embed = discord.Embed(
        title=CONFIG["weryfikacja_tytul"],
        description=CONFIG["weryfikacja_opis"],
        color=get_color("akcent"),
    )
    plik = prepare_embed_image(embed, "weryfikacja")
    embed.set_footer(text=CONFIG["footer"], icon_url=footer_icon(interaction.guild))
    msg, edytowano = await send_or_edit_panel(target, embed, VerifyView(), "weryfikacja", plik)
    CONFIG["channels"]["weryfikacja"] = target.id
    save_config()
    akcja_tekst = "zaktualizowany (edytowano istniejącą wiadomość)" if edytowano else "wysłany jako nowa wiadomość"
    await interaction.response.send_message(f"Panel weryfikacji {akcja_tekst} na {target.mention} ✅", ephemeral=True)


# ========================
#   /konfiguracja - JEDNA grupa komend zamiast wielu osobnych
# ========================

config_group = app_commands.Group(name="konfiguracja", description="[ADMIN] Konfiguracja bota")


@config_group.command(name="kolor", description="Zmienia kolor bocznego paska embedów")
@app_commands.describe(typ="Który embed", kolor="Kolor w formacie HEX, np. #FF0000")
@app_commands.choices(typ=[
    app_commands.Choice(name="Powitanie", value="powitanie"),
    app_commands.Choice(name="Pożegnanie", value="pozegnanie"),
    app_commands.Choice(name="Reszta (tickety / regulamin / weryfikacja)", value="akcent"),
])
@ADMIN_ONLY
async def config_kolor(interaction: discord.Interaction, typ: app_commands.Choice[str], kolor: str):
    try:
        parsed = hex_to_color(kolor)
    except ValueError:
        await interaction.response.send_message("Zły format koloru. Użyj np. `#FF0000`.", ephemeral=True)
        return
    CONFIG["colors"][typ.value] = kolor if kolor.startswith("#") else f"#{kolor}"
    save_config()
    embed = discord.Embed(title="Podgląd koloru", description=f"Ustawiono kolor dla: **{typ.name}**", color=parsed)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@config_group.command(name="rola", description="Ustawia rolę staffu / weryfikacji")
@app_commands.describe(typ="Która rola", rola="Rola z serwera")
@app_commands.choices(typ=[
    app_commands.Choice(name="Staff (dostęp do ticketów)", value="staff"),
    app_commands.Choice(name="Weryfikacja", value="weryfikacja"),
])
@ADMIN_ONLY
async def config_rola(interaction: discord.Interaction, typ: app_commands.Choice[str], rola: discord.Role):
    CONFIG["roles"][typ.value] = rola.id
    save_config()
    await interaction.response.send_message(f"Rola **{typ.name}** ustawiona na {rola.mention} ✅", ephemeral=True)


@config_group.command(name="kategoria_ticketow", description="Ustawia kategorię, w której tworzą się nowe tickety")
@app_commands.describe(kategoria="Kategoria kanałów")
@ADMIN_ONLY
async def config_kategoria_ticketow(interaction: discord.Interaction, kategoria: discord.CategoryChannel):
    CONFIG["ticket_category_id"] = kategoria.id
    save_config()
    await interaction.response.send_message(f"Nowe tickety będą tworzone w kategorii **{kategoria.name}** ✅", ephemeral=True)


@config_group.command(name="propozycje", description="Ustawia kanał, na którym wiadomości zamieniają się w propozycje z głosowaniem")
@app_commands.describe(kanal="Kanał, na którym mają działać propozycje")
@ADMIN_ONLY
async def config_propozycje(interaction: discord.Interaction, kanal: discord.TextChannel):
    CONFIG["channels"]["propozycje"] = kanal.id
    save_config()
    await interaction.response.send_message(
        f"Kanał propozycji ustawiony na {kanal.mention} ✅\nKażda wiadomość na tym kanale zamieni się w propozycję z głosowaniem ✅/❌.",
        ephemeral=True
    )


@config_group.command(name="obrazek", description="Podmienia banner powitania / pożegnania / ticketów / weryfikacji / propozycji")
@app_commands.describe(typ="Który obrazek zmieniamy", obrazek="Wklej nowy obrazek jako załącznik")
@app_commands.choices(typ=[
    app_commands.Choice(name="Powitanie", value="powitanie"),
    app_commands.Choice(name="Pożegnanie", value="pozegnanie"),
    app_commands.Choice(name="Panel ticketów", value="ticket"),
    app_commands.Choice(name="Wiadomość wewnątrz ticketu", value="ticket_wiadomosc"),
    app_commands.Choice(name="Weryfikacja", value="weryfikacja"),
    app_commands.Choice(name="Propozycje (miniaturka)", value="propozycja"),
])
@ADMIN_ONLY
async def config_obrazek(interaction: discord.Interaction, typ: app_commands.Choice[str], obrazek: discord.Attachment):
    if not obrazek.content_type or not obrazek.content_type.startswith("image/"):
        await interaction.response.send_message("To nie jest plik graficzny.", ephemeral=True)
        return

    # Usuwamy stary plik tego typu (mógł mieć inne rozszerzenie), żeby nie zaśmiecać dysku.
    for _stary in os.listdir(IMAGES_DIR):
        if os.path.splitext(_stary)[0] == typ.value:
            try:
                os.remove(os.path.join(IMAGES_DIR, _stary))
            except OSError:
                pass

    rozszerzenie = os.path.splitext(obrazek.filename)[1] or ".png"
    sciezka = os.path.join(IMAGES_DIR, f"{typ.value}{rozszerzenie}")
    dane = await obrazek.read()
    with open(sciezka, "wb") as f:
        f.write(dane)

    CONFIG["images"][typ.value] = sciezka
    save_config()

    embed = discord.Embed(title="Zapisano nowy obrazek ✅", description=f"Typ: **{typ.name}**\n(zapisany trwale na dysku - nie wygaśnie)", color=discord.Color.green())
    plik_podglad = discord.File(sciezka, filename=os.path.basename(sciezka))
    embed.set_image(url=f"attachment://{os.path.basename(sciezka)}")
    await interaction.response.send_message(embed=embed, file=plik_podglad, ephemeral=True)


@config_group.command(name="podglad", description="Pokazuje aktualną konfigurację bota")
@ADMIN_ONLY
async def config_podglad(interaction: discord.Interaction):
    guild = interaction.guild

    def ch(cid):
        c = guild.get_channel(cid) if cid else None
        return c.mention if c else "*nie ustawiono*"

    def rl(rid):
        r = guild.get_role(rid) if rid else None
        return r.mention if r else "*nie ustawiono*"

    def cat(cid):
        c = guild.get_channel(cid) if cid else None
        return c.name if c else "*nie ustawiono*"

    embed = discord.Embed(title="⚙️ Aktualna konfiguracja", color=get_color("akcent"))
    embed.add_field(name="Kanał powitań", value=ch(CONFIG["channels"]["powitanie"]), inline=True)
    embed.add_field(name="Kanał pożegnań", value=ch(CONFIG["channels"]["pozegnanie"]), inline=True)
    embed.add_field(name="Kanał panelu ticketów", value=ch(CONFIG["channels"]["ticket_panel"]), inline=True)
    embed.add_field(name="Kanał panelu weryfikacji", value=ch(CONFIG["channels"]["weryfikacja"]), inline=True)
    embed.add_field(name="Kanał propozycji", value=ch(CONFIG["channels"]["propozycje"]), inline=True)
    embed.add_field(name="Kategoria ticketów", value=cat(CONFIG["ticket_category_id"]), inline=True)
    embed.add_field(name="Rola staffu", value=rl(CONFIG["roles"]["staff"]), inline=True)
    embed.add_field(name="Rola weryfikacji", value=rl(CONFIG["roles"]["weryfikacja"]), inline=True)
    embed.add_field(name="Kolor powitania", value=CONFIG["colors"]["powitanie"], inline=True)
    embed.add_field(name="Kolor pożegnania", value=CONFIG["colors"]["pozegnanie"], inline=True)
    embed.add_field(name="Kolor akcentu", value=CONFIG["colors"]["akcent"], inline=True)
    kategorie = ", ".join(dane["etykieta"] for dane in CONFIG["ticket_kategorie"].values()) or "brak"
    embed.add_field(name="Kategorie ticketów", value=kategorie, inline=False)
    embed.set_footer(text=CONFIG["footer"])
    await interaction.response.send_message(embed=embed, ephemeral=True)





# ========================
#   INTERAKTYWNY PANEL KATEGORII (dropdown + przyciski, jak w tickecie)
#   Jedna wiadomość, która się "przełącza" - najpierw lista/dodawanie,
#   a po wybraniu istniejącej kategorii - jej edycja.
# ========================

def _kategoria_opis_linia(klucz: str, dane: dict) -> str:
    ile = len(dane.get("pytania", []))
    info = f"{ile} pytań w formularzu" if ile else "bez formularza (ticket od razu)"
    return f"**{dane['etykieta']}** `({klucz})` — {info}"


def render_kategoria_glowny():
    embed = discord.Embed(title="🗂️ Zarządzanie kategoriami ticketów", color=get_color("akcent"))
    if not CONFIG["ticket_kategorie"]:
        embed.description = "Brak kategorii. Kliknij **➕ Dodaj kategorię**, żeby stworzyć pierwszą."
    else:
        embed.description = "\n".join(_kategoria_opis_linia(k, d) for k, d in CONFIG["ticket_kategorie"].items())
    embed.set_footer(text="Wybierz kategorię z listy, żeby ją edytować, albo dodaj nową.")
    return embed, KategoriaGlownyView()


def render_kategoria_detail(klucz: str):
    dane = CONFIG["ticket_kategorie"].get(klucz)
    if dane is None:
        return render_kategoria_glowny()
    embed = discord.Embed(title=f"{dane['etykieta']}", description=f"Klucz: `{klucz}`", color=get_color("akcent"))
    pytania = dane.get("pytania", [])
    if pytania:
        tresc = "\n".join(
            f"**{i}.** {p['tresc']} _({'długa' if p['styl'] == 'paragraph' else 'krótka'}, "
            f"{'wymagane' if p.get('wymagane', True) else 'opcjonalne'})_"
            for i, p in enumerate(pytania, start=1)
        )
    else:
        tresc = "*Brak pytań — po kliknięciu tej kategorii ticket tworzy się od razu, bez formularza.*"
    embed.add_field(name="📝 Pytania formularza", value=tresc, inline=False)
    return embed, KategoriaDetailView(klucz)


def render_usun_pytanie(klucz: str):
    dane = CONFIG["ticket_kategorie"].get(klucz, {})
    embed = discord.Embed(
        title=f"🗑️ Usuń pytanie - {dane.get('etykieta', klucz)}",
        description="Wybierz pytanie do usunięcia z listy poniżej.",
        color=get_color("akcent"),
    )
    return embed, UsunPytanieView(klucz)


class KategoriaGlownyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        if CONFIG["ticket_kategorie"]:
            select = discord.ui.Select(
                placeholder="Wybierz kategorię, żeby ją edytować...",
                options=[
                    discord.SelectOption(label=dane["etykieta"][:100], value=k, description=f"klucz: {k}")
                    for k, dane in CONFIG["ticket_kategorie"].items()
                ][:25],
            )
            select.callback = self.on_select
            self.add_item(select)

        dodaj_btn = discord.ui.Button(label="➕ Dodaj kategorię", style=discord.ButtonStyle.success)
        dodaj_btn.callback = self.on_dodaj
        self.add_item(dodaj_btn)

    async def on_select(self, interaction: discord.Interaction):
        klucz = interaction.data["values"][0]
        embed, view = render_kategoria_detail(klucz)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_dodaj(self, interaction: discord.Interaction):
        await interaction.response.send_modal(NowaKategoriaModal())


class NowaKategoriaModal(discord.ui.Modal, title="Nowa kategoria ticketów"):
    def __init__(self):
        super().__init__()
        self.klucz_input = discord.ui.TextInput(label="Krótki identyfikator (bez spacji)", placeholder="np. sklep", max_length=50)
        self.etykieta_input = discord.ui.TextInput(label="Nazwa widoczna dla użytkownika", placeholder="np. 🛒 Sklep", max_length=100)
        self.add_item(self.klucz_input)
        self.add_item(self.etykieta_input)

    async def on_submit(self, interaction: discord.Interaction):
        klucz = str(self.klucz_input.value).lower().strip().replace(" ", "_")
        if klucz in CONFIG["ticket_kategorie"]:
            await interaction.response.send_message(f"Kategoria `{klucz}` już istnieje. Wybierz ją z listy, żeby edytować.", ephemeral=True)
            return
        CONFIG["ticket_kategorie"][klucz] = {"etykieta": str(self.etykieta_input.value), "pytania": []}
        save_config()
        embed, view = render_kategoria_detail(klucz)
        await interaction.response.edit_message(embed=embed, view=view)


class KategoriaDetailView(discord.ui.View):
    def __init__(self, klucz: str):
        super().__init__(timeout=300)
        self.klucz = klucz

        edytuj_btn = discord.ui.Button(label="✏️ Zmień nazwę", style=discord.ButtonStyle.primary, row=0)
        edytuj_btn.callback = self.on_edytuj
        self.add_item(edytuj_btn)

        dodaj_pytanie_btn = discord.ui.Button(label="➕ Dodaj pytanie", style=discord.ButtonStyle.success, row=0)
        dodaj_pytanie_btn.callback = self.on_dodaj_pytanie
        self.add_item(dodaj_pytanie_btn)

        if CONFIG["ticket_kategorie"].get(klucz, {}).get("pytania"):
            usun_pytanie_btn = discord.ui.Button(label="🗑️ Usuń pytanie", style=discord.ButtonStyle.secondary, row=0)
            usun_pytanie_btn.callback = self.on_usun_pytanie
            self.add_item(usun_pytanie_btn)

        usun_kat_btn = discord.ui.Button(label="🗑️ Usuń kategorię", style=discord.ButtonStyle.danger, row=1)
        usun_kat_btn.callback = self.on_usun_kategoria
        self.add_item(usun_kat_btn)

        wstecz_btn = discord.ui.Button(label="🔙 Wstecz do listy", style=discord.ButtonStyle.secondary, row=1)
        wstecz_btn.callback = self.on_wstecz
        self.add_item(wstecz_btn)

    async def on_edytuj(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ZmienNazweModal(self.klucz))

    async def on_dodaj_pytanie(self, interaction: discord.Interaction):
        if len(CONFIG["ticket_kategorie"].get(self.klucz, {}).get("pytania", [])) >= 5:
            await interaction.response.send_message("Ta kategoria ma już maksymalną liczbę pytań (5 - limit Discorda).", ephemeral=True)
            return
        await interaction.response.send_modal(DodajPytanieModal(self.klucz))

    async def on_usun_pytanie(self, interaction: discord.Interaction):
        embed, view = render_usun_pytanie(self.klucz)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_usun_kategoria(self, interaction: discord.Interaction):
        CONFIG["ticket_kategorie"].pop(self.klucz, None)
        save_config()
        embed, view = render_kategoria_glowny()
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_wstecz(self, interaction: discord.Interaction):
        embed, view = render_kategoria_glowny()
        await interaction.response.edit_message(embed=embed, view=view)


class UsunPytanieView(discord.ui.View):
    def __init__(self, klucz: str):
        super().__init__(timeout=300)
        self.klucz = klucz
        pytania = CONFIG["ticket_kategorie"].get(klucz, {}).get("pytania", [])
        select = discord.ui.Select(
            placeholder="Wybierz pytanie do usunięcia...",
            options=[discord.SelectOption(label=p["tresc"][:100], value=str(i)) for i, p in enumerate(pytania)][:25],
        )
        select.callback = self.on_select
        self.add_item(select)

        wstecz_btn = discord.ui.Button(label="🔙 Anuluj", style=discord.ButtonStyle.secondary)
        wstecz_btn.callback = self.on_wstecz
        self.add_item(wstecz_btn)

    async def on_select(self, interaction: discord.Interaction):
        idx = int(interaction.data["values"][0])
        pytania = CONFIG["ticket_kategorie"][self.klucz].get("pytania", [])
        if 0 <= idx < len(pytania):
            pytania.pop(idx)
            save_config()
        embed, view = render_kategoria_detail(self.klucz)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_wstecz(self, interaction: discord.Interaction):
        embed, view = render_kategoria_detail(self.klucz)
        await interaction.response.edit_message(embed=embed, view=view)


class ZmienNazweModal(discord.ui.Modal, title="Zmień nazwę kategorii"):
    def __init__(self, klucz: str):
        super().__init__()
        self.klucz = klucz
        obecna = CONFIG["ticket_kategorie"].get(klucz, {}).get("etykieta", "")
        self.nowa_etykieta = discord.ui.TextInput(label="Nowa nazwa", default=obecna, max_length=100)
        self.add_item(self.nowa_etykieta)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["ticket_kategorie"][self.klucz]["etykieta"] = str(self.nowa_etykieta.value)
        save_config()
        embed, view = render_kategoria_detail(self.klucz)
        await interaction.response.edit_message(embed=embed, view=view)


class DodajPytanieModal(discord.ui.Modal, title="Dodaj pytanie do formularza"):
    def __init__(self, klucz: str):
        super().__init__()
        self.klucz = klucz
        self.tresc_input = discord.ui.TextInput(label="Treść pytania", max_length=45, placeholder="np. Nick gracza")
        self.placeholder_input = discord.ui.TextInput(label="Podpowiedź w polu (opcjonalnie)", required=False, max_length=100)
        self.typ_input = discord.ui.TextInput(label="Typ odpowiedzi: krotkie / dlugie", default="krotkie", max_length=10)
        self.wymagane_input = discord.ui.TextInput(label="Czy wymagane? tak / nie", default="tak", max_length=5)
        self.add_item(self.tresc_input)
        self.add_item(self.placeholder_input)
        self.add_item(self.typ_input)
        self.add_item(self.wymagane_input)

    async def on_submit(self, interaction: discord.Interaction):
        styl = "paragraph" if str(self.typ_input.value).strip().lower().startswith("d") else "short"
        wymagane = not str(self.wymagane_input.value).strip().lower().startswith("n")
        pytania = CONFIG["ticket_kategorie"][self.klucz].setdefault("pytania", [])
        if len(pytania) >= 5:
            await interaction.response.send_message("Osiągnięto limit 5 pytań dla tej kategorii.", ephemeral=True)
            return
        pytania.append({
            "tresc": str(self.tresc_input.value),
            "styl": styl,
            "wymagane": wymagane,
            "placeholder": str(self.placeholder_input.value) if self.placeholder_input.value else "",
            "max_length": 1000 if styl == "paragraph" else 100,
        })
        save_config()
        embed, view = render_kategoria_detail(self.klucz)
        await interaction.response.edit_message(embed=embed, view=view)


@config_group.command(name="kategorie", description="Otwiera panel do zarządzania kategoriami ticketów (lista + przyciski)")
@ADMIN_ONLY
async def kategoria_panel(interaction: discord.Interaction):
    embed, view = render_kategoria_glowny()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ========================
#   PANEL KONFIGURACJI IGRZYSK ŚMIERCI
#   Jedna komenda, jedna wiadomość - dropdowny na kanały + przyciski do reszty ustawień.
# ========================

def render_igrzyska_panel():
    cfg = CONFIG["igrzyska"]
    embed = discord.Embed(title="🏹 Igrzyska Śmierci — konfiguracja", color=get_color("akcent"))

    def kanal_txt(cid):
        return f"<#{cid}>" if cid else "*nie ustawiono*"

    embed.add_field(name="📢 Kanał zapowiedzi", value=kanal_txt(cfg["kanal_zapowiedzi"]), inline=True)
    embed.add_field(name="📣 Kanał ogłoszeń", value=kanal_txt(cfg["kanal_ogloszenia"]), inline=True)
    embed.add_field(name="😀 Emoji reakcji", value=cfg["emoji_reakcja"], inline=True)
    embed.add_field(name="🔢 Wymagane reakcje", value=str(cfg["wymagane_reakcje"]), inline=True)
    embed.add_field(name="⏰ Godziny wysyłki", value=f"{', '.join(cfg['godziny'])}\n*(czas: Europe/Warsaw)*", inline=True)
    embed.add_field(name="🔁 Harmonogram", value=("🟢 Aktywny" if cfg["harmonogram_aktywny"] else "🔴 Wyłączony"), inline=True)

    def opisz_ping(typ_ping, rola_id):
        if typ_ping == "everyone":
            return "📢 @everyone"
        if typ_ping == "rola":
            return f"<@&{rola_id}>" if rola_id else "⚠️ Wybierz rolę w ustawieniach pingów"
        return "🔕 Brak pingu"

    embed.add_field(name="📌 Ping przy zapowiedzi", value=opisz_ping(cfg.get("typ_ping", "brak"), cfg.get("rola_ping_id")), inline=True)
    embed.add_field(name="📌 Ping przy starcie", value=opisz_ping(cfg.get("typ_ping_start", "everyone"), cfg.get("rola_ping_start_id")), inline=True)

    rcon_status = f"🟢 {cfg['rcon_host']}:{cfg['rcon_port']}" if cfg["rcon_host"] and cfg["rcon_haslo"] else "🔴 Brak konfiguracji"
    embed.add_field(name="🔌 RCON", value=rcon_status, inline=True)
    embed.add_field(name="🕹️ Komendy RCON", value=f"start: `{cfg['komenda_start']}`\nzamknij: `{cfg['komenda_zamknij']}`", inline=True)

    if cfg.get("w_trakcie"):
        status = "🟢 Igrzyska trwają (lobby otwarte)"
    elif cfg.get("aktualna_wiadomosc_id"):
        status = "🟡 Trwa zbieranie reakcji na aktualnej zapowiedzi"
    else:
        status = "⚪ Brak aktywnej zapowiedzi"
    embed.add_field(name="📊 Status", value=status, inline=False)
    embed.set_footer(text="Zmiany zapisują się automatycznie. Kanały wybierasz z list poniżej.")
    return embed, IgrzyskaPanelView()


class IgrzyskaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        cfg = CONFIG["igrzyska"]
        if cfg["harmonogram_aktywny"]:
            self.btn_toggle.label = "⏸️ Wyłącz harmonogram"
            self.btn_toggle.style = discord.ButtonStyle.danger
        else:
            self.btn_toggle.label = "▶️ Włącz harmonogram"
            self.btn_toggle.style = discord.ButtonStyle.success

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="📢 Kanał zapowiedzi (z reakcją)...", row=0)
    async def wybierz_kanal_zapowiedzi(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        CONFIG["igrzyska"]["kanal_zapowiedzi"] = select.values[0].id
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text],
                        placeholder="📣 Kanał ogłoszeń (@everyone)...", row=1)
    async def wybierz_kanal_ogloszen(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        CONFIG["igrzyska"]["kanal_ogloszenia"] = select.values[0].id
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="✏️ Treść zapowiedzi", style=discord.ButtonStyle.primary, row=2)
    async def btn_zapowiedz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ZapowiedzTrescModal())

    @discord.ui.button(label="✏️ Treść startu", style=discord.ButtonStyle.primary, row=2)
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StartTrescModal())

    @discord.ui.button(label="✏️ Treść zamknięcia", style=discord.ButtonStyle.primary, row=2)
    async def btn_zamkniecie(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ZamknieciTrescModal())

    @discord.ui.button(label="😀 Emoji i liczba", style=discord.ButtonStyle.secondary, row=2)
    async def btn_emoji(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmojiLiczbaModal())

    @discord.ui.button(label="⏰ Godzina", style=discord.ButtonStyle.secondary, row=2)
    async def btn_godzina(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GodzinaModal())

    @discord.ui.button(label="🔌 RCON", style=discord.ButtonStyle.secondary, row=3)
    async def btn_rcon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RconModal())

    @discord.ui.button(label="▶️ Włącz harmonogram", style=discord.ButtonStyle.success, row=3)
    async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = CONFIG["igrzyska"]
        cfg["harmonogram_aktywny"] = not cfg["harmonogram_aktywny"]
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="🧪 Wyślij zapowiedź teraz", style=discord.ButtonStyle.danger, row=3)
    async def btn_wyslij_teraz(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = CONFIG["igrzyska"]
        kanal = interaction.guild.get_channel(cfg["kanal_zapowiedzi"]) if cfg["kanal_zapowiedzi"] else None
        if not kanal:
            await interaction.response.send_message("Najpierw wybierz kanał zapowiedzi z listy na górze panelu.", ephemeral=True)
            return
        await wyslij_zapowiedz_igrzysk(kanal)
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)
        await interaction.followup.send(f"Zapowiedź wysłana na {kanal.mention} ✅", ephemeral=True)

    @discord.ui.button(label="🔔 Ustawienia pingów", style=discord.ButtonStyle.primary, row=3)
    async def btn_pingi(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, view = render_igrzyska_ping_panel()
        await interaction.response.edit_message(embed=embed, view=view)


def render_igrzyska_ping_panel():
    """Podpanel ustawień pingów - osobno dla zapowiedzi i osobno dla startu lobby."""
    cfg = CONFIG["igrzyska"]
    embed = discord.Embed(title="🔔 Igrzyska Śmierci — ustawienia pingów", color=get_color("akcent"))

    def opisz_ping(typ_ping, rola_id):
        if typ_ping == "everyone":
            return "📢 @everyone"
        if typ_ping == "rola":
            return f"<@&{rola_id}>" if rola_id else "⚠️ Wybierz rolę z listy poniżej"
        return "🔕 Brak pingu"

    embed.add_field(
        name="📢 Ping przy zapowiedzi",
        value=opisz_ping(cfg.get("typ_ping", "brak"), cfg.get("rola_ping_id")),
        inline=False,
    )
    embed.add_field(
        name="🎉 Ping przy starcie",
        value=opisz_ping(cfg.get("typ_ping_start", "everyone"), cfg.get("rola_ping_start_id")),
        inline=False,
    )
    embed.set_footer(text="Przyciski przełączają tryb (Brak → @everyone → Rola). Rolę wybierz z listy poniżej.")
    return embed, IgrzyskaPingPanelView()


class IgrzyskaPingPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        cfg = CONFIG["igrzyska"]

        typ_ping = cfg.get("typ_ping", "brak")
        etykiety_pingu = {"brak": "🔕 Zapowiedź - Ping: Brak", "rola": "🔔 Zapowiedź - Ping: Rola", "everyone": "📢 Zapowiedź - Ping: @everyone"}
        self.btn_typ_pingu.label = etykiety_pingu.get(typ_ping, "🔕 Zapowiedź - Ping: Brak")
        self.btn_typ_pingu.style = discord.ButtonStyle.secondary if typ_ping == "brak" else discord.ButtonStyle.primary

        typ_ping_start = cfg.get("typ_ping_start", "everyone")
        etykiety_pingu_start = {"brak": "🔕 Start - Ping: Brak", "rola": "🔔 Start - Ping: Rola", "everyone": "📢 Start - Ping: @everyone"}
        self.btn_typ_pingu_start.label = etykiety_pingu_start.get(typ_ping_start, "📢 Start - Ping: @everyone")
        self.btn_typ_pingu_start.style = discord.ButtonStyle.secondary if typ_ping_start == "brak" else discord.ButtonStyle.primary

    @discord.ui.button(label="🔕 Zapowiedź - Ping: Brak", style=discord.ButtonStyle.secondary, row=0)
    async def btn_typ_pingu(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = CONFIG["igrzyska"]
        kolejnosc = ["brak", "everyone", "rola"]
        obecny = cfg.get("typ_ping", "brak")
        nastepny = kolejnosc[(kolejnosc.index(obecny) + 1) % len(kolejnosc)] if obecny in kolejnosc else "brak"
        cfg["typ_ping"] = nastepny
        save_config()
        embed, view = render_igrzyska_ping_panel()
        await interaction.response.edit_message(embed=embed, view=view)
        if nastepny == "rola" and not cfg.get("rola_ping_id"):
            await interaction.followup.send(
                "Tryb zapowiedzi ustawiony na **Rola** - teraz wybierz konkretną rolę z listy niżej.",
                ephemeral=True,
            )

    @discord.ui.select(cls=discord.ui.RoleSelect,
                        placeholder="🔔 Rola do pingowania przy zapowiedzi...", row=1)
    async def wybierz_role_pingu(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        cfg = CONFIG["igrzyska"]
        cfg["rola_ping_id"] = select.values[0].id
        cfg["typ_ping"] = "rola"  # wybór roli automatycznie ustawia tryb pingu na "Rola"
        save_config()
        embed, view = render_igrzyska_ping_panel()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="📢 Start - Ping: @everyone", style=discord.ButtonStyle.primary, row=2)
    async def btn_typ_pingu_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = CONFIG["igrzyska"]
        kolejnosc = ["brak", "everyone", "rola"]
        obecny = cfg.get("typ_ping_start", "everyone")
        nastepny = kolejnosc[(kolejnosc.index(obecny) + 1) % len(kolejnosc)] if obecny in kolejnosc else "brak"
        cfg["typ_ping_start"] = nastepny
        save_config()
        embed, view = render_igrzyska_ping_panel()
        await interaction.response.edit_message(embed=embed, view=view)
        if nastepny == "rola" and not cfg.get("rola_ping_start_id"):
            await interaction.followup.send(
                "Tryb startu ustawiony na **Rola** - teraz wybierz konkretną rolę z listy niżej.",
                ephemeral=True,
            )

    @discord.ui.select(cls=discord.ui.RoleSelect,
                        placeholder="🎉 Rola do pingowania przy starcie lobby...", row=3)
    async def wybierz_role_pingu_start(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        cfg = CONFIG["igrzyska"]
        cfg["rola_ping_start_id"] = select.values[0].id
        cfg["typ_ping_start"] = "rola"  # wybór roli automatycznie ustawia tryb pingu na "Rola"
        save_config()
        embed, view = render_igrzyska_ping_panel()
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="⬅️ Wróć do panelu głównego", style=discord.ButtonStyle.secondary, row=4)
    async def btn_wroc(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class ZapowiedzTrescModal(discord.ui.Modal, title="Treść zapowiedzi Igrzysk"):
    def __init__(self):
        super().__init__()
        cfg = CONFIG["igrzyska"]
        self.tytul = discord.ui.TextInput(label="Tytuł", default=cfg["wiadomosc_zapowiedz_tytul"], max_length=256)
        self.tresc = discord.ui.TextInput(
            label="Treść (dostępne: {emoji} {wymagane})",
            style=discord.TextStyle.paragraph,
            default=cfg["wiadomosc_zapowiedz_tresc"][:4000],
            max_length=4000,
        )
        self.add_item(self.tytul)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["igrzyska"]["wiadomosc_zapowiedz_tytul"] = str(self.tytul.value)
        CONFIG["igrzyska"]["wiadomosc_zapowiedz_tresc"] = str(self.tresc.value)
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class StartTrescModal(discord.ui.Modal, title="Treść ogłoszenia startu (@everyone)"):
    def __init__(self):
        super().__init__()
        self.tresc = discord.ui.TextInput(
            label="Treść",
            style=discord.TextStyle.paragraph,
            default=CONFIG["igrzyska"]["wiadomosc_start_tresc"][:4000],
            max_length=4000,
        )
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["igrzyska"]["wiadomosc_start_tresc"] = str(self.tresc.value)
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class ZamknieciTrescModal(discord.ui.Modal, title="Treść zamknięcia lobby"):
    def __init__(self):
        super().__init__()
        self.tresc = discord.ui.TextInput(
            label="Treść",
            style=discord.TextStyle.paragraph,
            default=CONFIG["igrzyska"]["wiadomosc_zamkniecie_tresc"][:4000],
            max_length=4000,
        )
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        CONFIG["igrzyska"]["wiadomosc_zamkniecie_tresc"] = str(self.tresc.value)
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class EmojiLiczbaModal(discord.ui.Modal, title="Emoji i liczba wymaganych reakcji"):
    def __init__(self):
        super().__init__()
        cfg = CONFIG["igrzyska"]
        self.emoji = discord.ui.TextInput(label="Emoji reakcji", default=cfg["emoji_reakcja"], max_length=50)
        self.liczba = discord.ui.TextInput(label="Wymagana liczba reakcji", default=str(cfg["wymagane_reakcje"]), max_length=5)
        self.add_item(self.emoji)
        self.add_item(self.liczba)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            liczba = int(str(self.liczba.value).strip())
            if liczba < 1:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("Liczba reakcji musi być liczbą całkowitą większą od 0.", ephemeral=True)
            return
        CONFIG["igrzyska"]["emoji_reakcja"] = str(self.emoji.value).strip()
        CONFIG["igrzyska"]["wymagane_reakcje"] = liczba
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class GodzinaModal(discord.ui.Modal, title="Godziny automatycznej wysyłki"):
    def __init__(self):
        super().__init__()
        self.godziny = discord.ui.TextInput(
            label="Godziny (HH:MM, po przecinku, czas PL)",
            default=", ".join(CONFIG["igrzyska"]["godziny"]),
            max_length=100,
            placeholder="np. 18:00, 20:00",
        )
        self.add_item(self.godziny)

    async def on_submit(self, interaction: discord.Interaction):
        surowe = [g.strip() for g in str(self.godziny.value).split(",") if g.strip()]
        if not surowe:
            await interaction.response.send_message("Podaj przynajmniej jedną godzinę, np. `18:00`.", ephemeral=True)
            return
        for g in surowe:
            if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", g):
                await interaction.response.send_message(
                    f"Zły format godziny: `{g}`. Podaj godziny jako HH:MM oddzielone przecinkami, np. `18:00, 20:00`.",
                    ephemeral=True,
                )
                return
        # usuwamy duplikaty, zachowując kolejność
        godziny_unikalne = list(dict.fromkeys(surowe))
        CONFIG["igrzyska"]["godziny"] = godziny_unikalne
        save_config()
        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)


class RconModal(discord.ui.Modal, title="Konfiguracja RCON serwera Minecraft"):
    def __init__(self):
        super().__init__()
        cfg = CONFIG["igrzyska"]
        self.host = discord.ui.TextInput(label="Adres IP / host serwera", default=cfg["rcon_host"], max_length=100)
        self.port = discord.ui.TextInput(label="Port RCON", default=str(cfg["rcon_port"]), max_length=6)
        self.haslo = discord.ui.TextInput(label="Hasło RCON", default=cfg["rcon_haslo"], max_length=200)
        self.komenda_start = discord.ui.TextInput(label="Komenda startu lobby", default=cfg["komenda_start"], max_length=100)
        self.komenda_zamknij = discord.ui.TextInput(label="Komenda zamknięcia lobby", default=cfg["komenda_zamknij"], max_length=100)
        self.add_item(self.host)
        self.add_item(self.port)
        self.add_item(self.haslo)
        self.add_item(self.komenda_start)
        self.add_item(self.komenda_zamknij)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            port = int(str(self.port.value).strip())
        except ValueError:
            await interaction.response.send_message("Port musi być liczbą.", ephemeral=True)
            return
        CONFIG["igrzyska"]["rcon_host"] = str(self.host.value).strip()
        CONFIG["igrzyska"]["rcon_port"] = port
        CONFIG["igrzyska"]["rcon_haslo"] = str(self.haslo.value)
        CONFIG["igrzyska"]["komenda_start"] = str(self.komenda_start.value).strip()
        CONFIG["igrzyska"]["komenda_zamknij"] = str(self.komenda_zamknij.value).strip()
        save_config()

        embed, view = render_igrzyska_panel()
        await interaction.response.edit_message(embed=embed, view=view)

        sukces, wynik = await rcon_wykonaj("list")
        if sukces:
            await interaction.followup.send(f"Zapisano ✅ Test połączenia RCON udany: `{wynik}`", ephemeral=True)
        else:
            await interaction.followup.send(f"Zapisano, ale test połączenia RCON nie powiódł się: {wynik}", ephemeral=True)


@config_group.command(name="igrzyska", description="Otwiera panel konfiguracji Igrzysk Śmierci (kanały, treści, RCON, harmonogram)")
@ADMIN_ONLY
async def config_igrzyska(interaction: discord.Interaction):
    embed, view = render_igrzyska_panel()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


bot.tree.add_command(config_group)


if __name__ == "__main__":
    bot.run(TOKEN)

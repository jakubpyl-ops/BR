# Instrukcja: jak uruchomić bota IGRZYSKA FFA

## KROK 1 — Stwórz aplikację bota w Discord
1. Wejdź na https://discord.com/developers/applications
2. Kliknij **New Application**, nadaj nazwę (np. "Igrzyska FFA Bot").
3. W lewym menu wejdź w **Bot** → **Add Bot**.
4. W sekcji **Privileged Gateway Intents** włącz:
   - **Server Members Intent** (WYMAGANE do powitań/pożegnań)
   - **Message Content Intent**
5. Kliknij **Reset Token** → **Copy** — to jest Twój `DISCORD_TOKEN`. Nikomu go nie pokazuj.

## KROK 2 — Zaproś bota na serwer
1. W menu po lewej wejdź w **OAuth2 → URL Generator**.
2. Zaznacz scope: `bot` oraz `applications.commands`.
3. W permissions zaznacz: `Administrator` (najprościej) albo minimalnie: Manage Channels, Send Messages, Embed Links, Manage Roles, Read Message History.
4. Skopiuj wygenerowany link, wklej w przeglądarkę, wybierz swój serwer i zatwierdź.

## KROK 3 — Zbierz potrzebne ID
Włącz w Discordzie **Ustawienia → Zaawansowane → Tryb dewelopera**.
Potem kliknij prawym przyciskiem na:
- kanał powitań → **Kopiuj ID** → to `WELCOME_CHANNEL_ID`
- kanał pożegnań (możesz użyć tego samego lub innego) → `GOODBYE_CHANNEL_ID`
- kategorię, w której mają powstawać tickety → `TICKET_CATEGORY_ID`
- rolę administracji → `STAFF_ROLE_ID`
- rolę nadawaną po weryfikacji (np. "Zweryfikowany") → `VERIFY_ROLE_ID`

## KROK 4 — Wrzuć kod na GitHub
1. Załóż konto na https://github.com jeśli nie masz.
2. Stwórz nowe repozytorium (Nowy → Repository), np. "igrzyska-ffa-bot".
3. Wgraj tam pliki: `bot.py`, `requirements.txt`, `Procfile` (te, które Ci przygotowałem).

## KROK 5 — Hosting na Railway (darmowy start)
1. Wejdź na https://railway.app i zaloguj się przez GitHub.
2. Kliknij **New Project → Deploy from GitHub repo** i wybierz swoje repozytorium.
3. Railway wykryje Pythona automatycznie.
4. Wejdź w zakładkę **Variables** i dodaj zmienne środowiskowe (to jest bezpieczne miejsce na token, NIE wpisuj go do kodu):
   - `DISCORD_TOKEN` = twój token z kroku 1
   - `WELCOME_CHANNEL_ID` = ID kanału powitań
   - `GOODBYE_CHANNEL_ID` = ID kanału pożegnań
   - `TICKET_CATEGORY_ID` = ID kategorii ticketów
   - `STAFF_ROLE_ID` = ID roli administracji
5. Railway sam zbuduje projekt i uruchomi `python bot.py` (dzięki plikowi Procfile).
6. Sprawdź zakładkę **Deployments → Logs** — powinieneś zobaczyć: `Zalogowano jako ... - bot działa!`

## KROK 5.5 — Skonfiguruj wszystko z poziomu Discorda

Wszystkie poniższe komendy wymagają uprawnień administratora i działają od razu, bez restartu bota:

**Obrazki (5 bannerów):**
```
/ustaw_obrazek typ:Powitanie obrazek:(załącz plik)
/ustaw_obrazek typ:Pożegnanie obrazek:(załącz plik)
/ustaw_obrazek typ:"Panel ticketów" obrazek:(załącz plik)
/ustaw_obrazek typ:"Wiadomość wewnątrz ticketu" obrazek:(załącz plik)
/ustaw_obrazek typ:Weryfikacja obrazek:(załącz plik)
```

**Teksty (otwierają formularz do wypełnienia):**
```
/edytuj_regulamin          → treść regulaminu
/edytuj_powitanie          → tytuł + treść wiadomości powitalnej (placeholdery: {mention} {nazwa} {ilosc})
/edytuj_pozegnanie         → tytuł + treść wiadomości pożegnalnej (te same placeholdery)
/edytuj_ticket_panel       → tytuł + opis panelu ticketów (dropdown z kategoriami)
/edytuj_ticket_wiadomosc   → treść wiadomości pojawiającej się WEWNĄTRZ nowo otwartego ticketu (placeholdery: {mention} {nazwa})
/edytuj_weryfikacje        → tytuł + opis panelu weryfikacji
```

**Kategorie ticketów:**
```
/dodaj_kategorie klucz:sklep etykieta:🛒 Sklep
/usun_kategorie klucz:sklep
/lista_kategorii
```
Po dodaniu/usunięciu kategorii wyślij ponownie `/ticket_panel`, żeby menu się zaktualizowało.

**Panele do wysłania na kanały (raz, ręcznie):**
```
/ticket_panel          → wysyła panel tworzenia ticketów na aktualnym kanale
/panel_weryfikacji     → wysyła panel z przyciskiem "Zweryfikuj się" na aktualnym kanale
```
Zalecane: wyślij `/panel_weryfikacji` na osobnym kanale typu `#weryfikacja`, widocznym dla niezweryfikowanych, i skonfiguruj uprawnienia kanałów tak, by rola `VERIFY_ROLE_ID` odblokowywała resztę serwera.

**Podgląd wszystkiego naraz:**
```
/pokaz_konfiguracje
```

⚠️ **Ważne o trwałości:** cała konfiguracja (obrazki, teksty, kategorie) zapisuje się w pliku `config.json` na dysku. Na Railway ten dysk domyślnie kasuje się przy każdym nowym wdrożeniu kodu (redeploy). Jeśli chcesz, żeby ustawienia przetrwały redeploy:
1. W Railway wejdź w swój serwis → **Settings → Volumes → Add Volume**.
2. Zamontuj go np. pod `/data`.
3. Dodaj zmienną środowiskową `CONFIG_PATH` = `/data/config.json`.

## KROK 6 — Ustaw panel ticketów
Na serwerze, na kanale gdzie ma być panel tworzenia ticketów, wpisz komendę slash:
```
/ticket_panel
```
(musisz mieć uprawnienia administratora). Bot wyśle wiadomość z listą rozwijaną do wyboru kategorii.

## O limitach (żeby nic Ci nie "wygasło")
- **Railway free trial**: daje ~500h/miesiąc i 5$ jednorazowego kredytu. Jeśli bot ma pracować 24/7 bez przerwy, po wyczerpaniu limitu trzeba podpiąć kartę (parę groszy miesięcznie za mały bota) albo przenieść się na darmowy VPS (np. Oracle Cloud Free Tier — działa bez limitu czasowego, ale wymaga ręcznej konfiguracji Linuksa).
- **Discord API rate limity**: biblioteka discord.py sama pilnuje limitów zapytań do Discorda — nie musisz nic robić, kod jest już na to odporny.
- Jeśli zobaczysz błąd `429` w logach — to normalne, biblioteka automatycznie poczeka i wyśle ponownie.

## Co możesz jeszcze dodać
- Automatyczne role powitalne (`member.add_roles(...)`)
- Logi moderacyjne (ban/kick/mute)
- Komendę `/stats` z liczbą graczy online na serwerze Minecraft

Daj znać jeśli chcesz żebym dodał którąś z tych rzeczy.

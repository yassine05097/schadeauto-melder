# Schadeauto-melder

Krijg een melding op je telefoon zodra er op **schadeautos.nl** een nieuwe
personenauto online komt met bouwjaar **2022 of nieuwer**. Tik op de melding en de
advertentie gaat open.

Voorbeeld:

```
🚗 Seat Leon (2023)
SPORTSTOURER 1.5 TSI MHEV FR BUSINESS DSG
€ 15.750 · 113.368 km · hybride benzine
https://www.schadeautos.nl/nl/schade/personenautos/...
```

## Hoe het werkt

1. Elke minuut kijkt de melder naar de nieuwste advertenties op schadeautos.nl
   (de lijst "nieuwste eerst", dezelfde die je in de browser ziet).
2. Hij onthoudt welke advertenties hij al gezien heeft (in `gezien.json`).
3. Staat er een nieuwe advertentie tussen met bouwjaar (1ste toelating) 2022 of
   later, dan stuurt hij je meteen een melding.

De eerste keer doet hij een *nulmeting*: alles wat er al stond wordt onthouden
zonder melding. Daarna krijg je alleen meldingen voor nieuwe auto's.

## Laptop uit of in slaapstand?

De melder werkt alleen als je laptop **aan** staat en **niet slaapt**.

- Gaat je laptop weer aan, dan kijkt hij meteen de nieuwste 180 advertenties na
  (instelling `max_paginas`). Auto's van 2022+ die intussen online kwamen krijg je
  dan alsnog, alleen later. Na een hele dag uit kunnen dat er meer zijn dan 180;
  de oudste mis je dan.
- Slaapstand uitzetten: *Instellingen → Systeem → Energie en batterij →
  Scherm, slaapstand* → bij "aangesloten" de slaapstand op **Nooit**.
- Altijd meldingen, ook als je laptop uit is: zie **Ook als je laptop uit staat**.

## Welke app?

| App | Snelheid | Foto | Instellen |
|---|---|---|---|
| **ntfy** | binnen een minuut | ja | `instellen.bat` |
| **WhatsApp** (via CallMeBot) | vaak 5-15 minuten later (gratis dienst, wachtrij) | nee, wel tekst + link | `instellen-whatsapp.bat` |
| **Telegram** | binnen een minuut | ja, met knop | `instellen-telegram.bat` |

Staan er meerdere ingesteld, dan krijg je elke melding via allemaal.

**ntfy op iPhone geeft geen melding in beeld?** Controleer *Instellingen → ntfy →
Berichtgeving* (alles aan), verwijder je kanaal in de app en abonneer opnieuw, of
installeer de app opnieuw en tik op *Sta toe*. Helpt dat niet, gebruik dan Telegram.

## Installatie

1. **Kies je app(s)** en dubbelklik het bijbehorende `instellen…bat`-bestand. Volg
   de stappen op het scherm. Aan het eind krijg je een testmelding
   *"Schadeauto-melder werkt!"*.
   - **ntfy:** installeer de app *ntfy*, abonneer je (knop **+**) op de kanaalnaam
     die op je scherm staat. Houd die naam geheim.
   - **WhatsApp:** sla het nummer van de CallMeBot-bot op (staat op
     [callmebot.com](https://www.callmebot.com/blog/free-api-whatsapp-messages/),
     met +34 ervoor), stuur het via WhatsApp `I allow callmebot to send me messages`
     en vul daarna je eigen nummer en de *apikey* in die je terugkrijgt.
   - **Telegram:** maak via **@BotFather** een bot (`/newbot`) en plak het token.
     Tip: doe dit op je pc via [web.telegram.org](https://web.telegram.org).
2. **Starten:** dubbelklik `automatisch-starten.bat`. De melder draait dan
   onzichtbaar elke minuut, ook na een herstart. Liever in een venster om even te
   proberen? Gebruik `start-melder.bat` (stopt als je het venster sluit).
3. **Stoppen:** dubbelklik `automatisch-stoppen.bat`.

Map verplaatst of de melder bijgewerkt (nieuwe bestanden)? Dubbelklik dan opnieuw op
`automatisch-starten.bat` in de map.

## Instellingen aanpassen

Open `config.json` met Kladblok (sla daarna op; de volgende minuut geldt het):

| Instelling | Standaard | Betekenis |
|---|---|---|
| `min_bouwjaar` | `2022` | Laagste bouwjaar waarvoor je een melding krijgt. |
| `categorieen` | `["personenautos"]` | Ook bestelwagens? Gebruik `["personenautos", "bestelwagens"]`. |
| `meld_opnieuw_geplaatst` | `true` | Ook een melding als een oudere advertentie opnieuw bovenaan gezet is (vaak een prijsverlaging). De melding begint dan met "Opnieuw geplaatst". `false` = alleen echt nieuwe advertenties. |
| `max_paginas` | `15` | Hoeveel pagina's (12 advertenties per stuk) hij maximaal nakijkt, bijvoorbeeld nadat je laptop uit stond. |
| `interval_minuten` | `1` | Hoe vaak `start-melder.bat` kijkt. De achtergrondtaak kijkt altijd elke minuut. |
| `ntfy_topic` | (jouw kanaal) | Leegmaken = geen ntfy-meldingen meer. |
| `whatsapp_telefoon`, `whatsapp_apikey` | (jouw gegevens) | Leegmaken = geen WhatsApp meer. |
| `telegram_bot_token`, `telegram_chat_id` | (jouw gegevens) | Leegmaken = geen Telegram meer. |

Typfout gemaakt? Dan staat de foutmelding in `melder.log` en krijg je geen
meldingen tot het is hersteld.

## Als er iets misgaat

- **Logboek:** alles staat in `melder.log` in deze map.
- **Melding lukt even niet** (storing bij ntfy, WhatsApp of Telegram): de melder
  probeert alleen die app elke minuut opnieuw, zolang hij draait. Hij geeft pas op
  na minstens 30 pogingen én 6 uur; dat staat dan in `melder.log`.
- **Eén app blijft mislukken** (bijvoorbeeld WhatsApp): je krijgt één waarschuwing via
  de andere app, met de reden. Zet CallMeBot je op pauze ("Your Account is Paused"),
  stuur dan via WhatsApp het woord `resume` naar de CallMeBot-bot. Om dat te voorkomen
  stuurt de melder hooguit 5 WhatsApp-berichten per ronde, en WhatsApp-kopieën die
  ouder zijn dan 3 uur (en die je al via een andere app kreeg) slaat hij over.
- **schadeautos.nl onbereikbaar of veranderd:** na een half uur krijg je één
  waarschuwing *"Schadeauto-melder: storing"*, en een bericht zodra het weer werkt.
- **Testmelding sturen:** `python melder.py --test` (opdrachtvenster in deze map).
- **Kijken wat hij nu zou melden**, zonder iets te versturen of op te slaan:
  `python melder.py --dry-run` (toont de 2022+ auto's die nog niet gemeld zijn
  op de eerste pagina; meestal dus niets. Direct na het installeren zegt hij
  alleen dat de eerste ronde een nulmeting wordt).
- **Opnieuw beginnen** (nieuwe nulmeting): verwijder `gezien.json`.

## Ook als je laptop uit staat

**Kies één plek.** Draait de melder ergens anders (GitHub, een oude pc of een
Raspberry Pi), zet hem dan op je laptop uit met `automatisch-stoppen.bat`, anders
krijg je elke auto dubbel. Doe dat pas als de nieuwe plek werkt.

**Gratis, maar langzamer: GitHub.** GitHub draait de melder hooguit elke
5 minuten, en vaak een paar minuten later dan gepland (melding 5-15 minuten na
plaatsing). Alles wat je moet uploaden staat in de map `schadeauto-melder-github`.

1. Maak een gratis account op github.com en een **nieuwe public repository**
   (bij private is het gratis tegoed te klein; je geheime gegevens blijven ook bij
   public verborgen).
2. Klik op **uploading an existing file** en sleep alles uit
   `schadeauto-melder-github` erin (4 bestanden, inclusief `.github`). Klik
   **Commit changes**. Upload nooit `config.json`.
3. **Settings → Secrets and variables → Actions → New repository secret.** De
   waarden staan in `config.json` (open met Kladblok); kopieer alleen wat tussen de
   aanhalingstekens staat:

   | Secret in GitHub | Waarde uit config.json |
   |---|---|
   | `NTFY_TOPIC` | `ntfy_topic` |
   | `WHATSAPP_TELEFOON` | `whatsapp_telefoon` |
   | `WHATSAPP_APIKEY` | `whatsapp_apikey` |
   | `TELEGRAM_BOT_TOKEN` | `telegram_bot_token` (alleen als je Telegram gebruikt) |
   | `TELEGRAM_CHAT_ID` | `telegram_chat_id` (alleen als je Telegram gebruikt) |

   Ander bouwjaar? Tabblad *Variables*: `MIN_BOUWJAAR`.
4. Tabblad **Actions** → "schadeauto-melder" → **Run workflow**, met het vinkje
   **"Alleen een testmelding sturen"** aan. Je krijgt *"Schadeauto-melder werkt!"*.
   Wordt de run rood, dan klopt een secret niet.
5. Nog een keer **Run workflow**, nu zonder vinkje: dat is de nulmeting. Is die groen,
   zet dan je laptop-melder uit met `automatisch-stoppen.bat`.

Blijft een melding steeds mislukken, dan wordt de run rood en stuurt GitHub je een
e-mail.

**Snel (elke minuut), maar je hebt een apparaat nodig dat altijd aan staat:**
- een oude Windows-laptop of -pc: kopieer deze map erheen en dubbelklik daar
  `automatisch-starten.bat`;
- een Raspberry Pi of kleine cloudserver (vanaf ca. 4 euro per maand) met Linux:
  kopieer de map naar je thuismap (zodat hij `~/schadeauto-melder` heet), typ
  `crontab -e` en voeg deze regel toe:

  ```
  * * * * * cd "$HOME/schadeauto-melder" && python3 melder.py >/dev/null 2>&1
  ```

  Na 2 minuten moet in die map `melder.log` staan; zo niet, dan klopt het pad niet.

## mobile.de

Deze melder kan mobile.de niet uitlezen: mobile.de blokkeert dat en verbiedt het in
de voorwaarden. De snelle, gratis en officiële manier is de **mobile.de-app** met een
opgeslagen zoekopdracht:

1. Installeer de app **mobile.de** en maak een gratis account aan.
2. Stel de zoekopdracht in op je pc via [mobile.de/nl](https://www.mobile.de/nl)
   (makkelijker dan in de app): **Meer filters** →
   - **Eerste registratie: van 2022**
   - **Beschadigde voertuigen:** staat standaard op *Niet weergeven*. Zet op
     **Alleen weergeven** voor alleen schadeauto's (of *Willekeurig* voor alles;
     voeg dan filters zoals land, prijs of merk toe, anders krijg je er duizenden).
   - Klik op **Deze zoekopdracht opslaan**.
3. Log in de app in met hetzelfde account, ga naar **Mijn zoekopdrachten / Meine
   Suchen** en zet de **meldingen** aan. Sta meldingen toe op je iPhone.

mobile.de belooft een melding zodra een nieuwe advertentie online komt.

## Netjes blijven

De melder bekijkt meestal alleen de eerste pagina van de openbare lijst, één keer
per minuut, gecomprimeerd (ongeveer 30 KB). Dat is minder dan één bezoeker die de
site open heeft. Zet het interval niet korter dan een minuut.

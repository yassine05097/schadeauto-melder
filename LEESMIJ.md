# Schadeauto-melder

Krijg een melding op je telefoon zodra er op **schadeautos.nl** een nieuwe
personenauto online komt met bouwjaar **2022 of nieuwer**. Tik op de melding en de
advertentie gaat open. De melder draait op **GitHub**, dus ook als je pc uit staat.

Voorbeeld:

```
🚗 Seat Leon (2023)
SPORTSTOURER 1.5 TSI MHEV FR BUSINESS DSG
€ 15.750 · 113.368 km · hybride benzine
https://www.schadeautos.nl/nl/schade/personenautos/...
```

## Hoe het werkt

1. Elke 5 minuten start GitHub de melder (aangestuurd door cron-job.org, zie hieronder).
2. De melder bekijkt de nieuwste advertenties op schadeautos.nl en onthoudt wat hij
   al gezien heeft (in `gezien.json` in je GitHub-repository).
3. Staat er een nieuwe advertentie tussen met bouwjaar (1ste toelating) 2022 of
   later, dan stuurt hij je een melding.

**Welke lijst hij leest.** Normaal leest hij de zoekresultaten van schadeautos.nl
(nieuwste eerst, meerdere pagina's). Sinds november 2026 laat schadeautos.nl die
zoekresultaten alleen nog aan gewone browsers zien. Dan leest de melder de openbare
lijst met de **5 nieuwste** personenauto's op schadeautos.nl/nl/schadeauto. Elk uur
kijkt hij of de zoekresultaten weer werken; zo ja, dan gebruikt hij die weer.
Komen er binnen 5 minuten meer dan 5 auto's tegelijk online, dan kan hij er een paar
missen (dat staat dan in het logboek van de run).

De eerste keer doet hij een *nulmeting*: alles wat er al stond wordt onthouden
zonder melding. Daarna krijg je alleen meldingen voor nieuwe auto's.

## Elke 5 minuten: cron-job.org

GitHub start geplande taken van gratis accounts vaak uren te laat. Daarom laat je
de gratis dienst **cron-job.org** GitHub elke 5 minuten een seintje geven.

**1. Maak in GitHub een sleutel (token) die alleen deze taak mag starten.**
- Ga naar [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new).
- *Token name:* `cron-job schadeauto-melder`
- *Expiration:* kies de langste termijn. Zet in je agenda dat je hem dan vernieuwt.
- *Repository access:* **Only select repositories** → kies `schadeauto-melder`.
- *Permissions* → *Repository permissions* → **Actions** → **Read and write**.
- Klik **Generate token** en kopieer de code (begint met `github_pat_`). Je ziet
  hem maar één keer. Deel hem met niemand.

**2. Maak een gratis account op [cron-job.org](https://cron-job.org)** en klik op
**Create cronjob**:
- *Title:* `schadeauto-melder`
- *URL:*
  `https://api.github.com/repos/yassine05097/schadeauto-melder/actions/workflows/melder.yml/dispatches`
- *Execution schedule:* **Every 5 minutes**
- Tabblad **Advanced**:
  - *Request method:* **POST**
  - *Headers* (drie stuks, met **Add**):

    | Key | Value |
    |---|---|
    | `Accept` | `application/vnd.github+json` |
    | `Authorization` | `Bearer ` + je token (dus `Bearer github_pat_...`) |
    | `X-GitHub-Api-Version` | `2022-11-28` |

  - *Request body:* `{"ref":"main"}`
- Klik **Test run**: als antwoord moet **204** verschijnen. Klik dan **Create**.

Daarna zie je in GitHub onder **Actions** elke 5 minuten een nieuwe run.

## Welke app?

| App | Foto | Instellen |
|---|---|---|
| **ntfy** | ja | secret `NTFY_TOPIC` |
| **WhatsApp** (via CallMeBot, gratis, vaak een paar minuten vertraging) | nee, wel tekst + link | secrets `WHATSAPP_TELEFOON` en `WHATSAPP_APIKEY` |
| **Telegram** | ja, met knop | secrets `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID` |

Secrets staan in GitHub onder **Settings → Secrets and variables → Actions**. Staan
er meerdere ingesteld, dan krijg je elke melding via allemaal.

**Ander bouwjaar?** Zelfde plek, tabblad *Variables*: `MIN_BOUWJAAR`, bijvoorbeeld `2023`.

**Testmelding:** **Actions** → "schadeauto-melder" → **Run workflow** → vinkje
**"Alleen een testmelding sturen"** aan → **Run workflow**.

## Als er iets misgaat

- **Logboek:** klik in GitHub op **Actions** en dan op een run.
- **Melding lukt even niet** (storing bij ntfy, WhatsApp of Telegram): de melder
  probeert alleen die app later opnieuw. Hij geeft pas op na minstens 30 pogingen
  én 6 uur.
- **Eén app blijft mislukken** (bijvoorbeeld WhatsApp): je krijgt één waarschuwing via
  de andere app, met de reden. Daarna probeert hij die app nog maar één keer per uur.
  Zet CallMeBot je op pauze ("Your Account is Paused"), stuur dan via WhatsApp het
  woord `resume` naar de CallMeBot-bot (+34 623 80 11 90). De melder stuurt hooguit
  5 WhatsApp-berichten per ronde, en WhatsApp-kopieën die ouder zijn dan 3 uur (en
  die je al via een andere app kreeg) slaat hij over.
- **schadeautos.nl onbereikbaar of veranderd:** na een half uur krijg je één
  waarschuwing *"Schadeauto-melder: storing"*, en een bericht zodra het weer werkt.
  De runs blijven groen; alleen als ook die waarschuwing nergens aankomt, wordt de run
  rood en stuurt GitHub je een e-mail.
- **Geen runs meer in Actions?** Kijk op cron-job.org of je cronjob nog aan staat
  (die gaat uit na 25 mislukte pogingen, bijvoorbeeld als je token verlopen is).
- **Opnieuw beginnen** (nieuwe nulmeting): verwijder `gezien.json` in je repository.

## Op je eigen pc (niet in gebruik)

De map `schadeauto-melder` op je Bureaublad kan de melder ook op je pc draaien
(`instellen*.bat`, `automatisch-starten.bat`). Dat staat nu **uit**: de melder draait
op GitHub. Zet hem niet op beide plekken aan, anders krijg je alles dubbel.

## mobile.de

Deze melder kan mobile.de niet uitlezen: mobile.de blokkeert dat en verbiedt het in
de voorwaarden. De snelle, gratis en officiële manier is de **mobile.de-app** met een
opgeslagen zoekopdracht:

1. Installeer de app **mobile.de** en maak een gratis account aan.
2. Stel de zoekopdracht in op je pc via [mobile.de/nl](https://www.mobile.de/nl):
   **Meer filters** → **Eerste registratie: van 2022**; **Beschadigde voertuigen** op
   **Alleen weergeven** (of *Willekeurig* voor alles, met extra filters) →
   **Deze zoekopdracht opslaan**.
3. Log in de app in met hetzelfde account, ga naar **Mijn zoekopdrachten** en zet de
   **meldingen** aan.

## Netjes blijven

De melder vraagt elke 5 minuten één openbare pagina op (en één keer per uur de
zoekpagina), gecomprimeerd. Dat is minder dan één bezoeker die de site open heeft.
Zet cron-job.org niet vaker dan elke 5 minuten.

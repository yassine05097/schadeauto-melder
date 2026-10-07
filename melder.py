#!/usr/bin/env python3
"""Schadeauto-melder: stuurt een pushmelding naar je telefoon (ntfy-app en/of WhatsApp)
zodra er op schadeautos.nl een nieuwe auto online komt met een bouwjaar boven een grens.

Alleen standaard-Python, geen extra pakketten nodig.

Gebruik:
    python melder.py --instellen            ntfy-app instellen en een testmelding sturen
    python melder.py --instellen-whatsapp   WhatsApp (via CallMeBot) instellen
    python melder.py --test                 stuur een testmelding
    python melder.py --loop                 blijven controleren, elke minuut
    python melder.py                        een keer controleren (Taakplanner / GitHub Actions)
    python melder.py --dry-run              laat zien wat er nu gemeld zou worden, zonder te versturen
"""

import argparse
import gzip
import html
import http.client
import json
import logging
import logging.handlers
import os
import re
import secrets
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASIS_URL = "https://www.schadeautos.nl"
# Zoekresultaten "schade", nieuwste advertenties eerst. Na de soort volgt 1 (= schade),
# dan het categorienummer. Laatste getal = paginanummer (0 = eerste pagina).
ZOEK_URL = BASIS_URL + "/nl/zoek/schade/{slug}/1/{categorie_id}/0/0/0/0/1/{pagina}"
CATEGORIEEN = {
    "personenautos": 1,
    "bestelwagens": 2,
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 schadeauto-melder/1.0"
)
CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
CALLMEBOT_UITLEG = "https://www.callmebot.com/blog/free-api-whatsapp-messages/"
TELEGRAM_API = "https://api.telegram.org"

MAP = os.path.dirname(os.path.abspath(__file__))
CONFIG_BESTAND = os.path.join(MAP, "config.json")
STATUS_BESTAND = os.path.join(MAP, "gezien.json")
LOG_BESTAND = os.path.join(MAP, "melder.log")
SLOT_BESTAND = os.path.join(MAP, ".melder.lock")

MAX_ONTHOUDEN = 20000            # zoveel advertentie-ID's onthouden we maximaal
MAX_WACHTTIJD = 6 * 3600         # een melding die zo lang blijft mislukken geven we op...
MIN_POGINGEN = 30                # ...maar pas na minstens zoveel echte pogingen (laptop kan uit staan)
VERZEND_BUDGET = 200             # na zoveel seconden versturen: rest volgende ronde
STORING_MELDEN_NA = 30 * 60      # website zo lang onleesbaar: stuur één waarschuwing
# Advertentie-ID's lopen op. Staat er bovenaan een ID dat ruim onder het hoogste bekende
# ID ligt, dan is het een oudere advertentie die opnieuw geplaatst is (vaak prijsverlaging).
OPNIEUW_GEPLAATST_MARGE = 5000

STANDAARD_CONFIG = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "ntfy_topic": "",
    "ntfy_server": "https://ntfy.sh",
    "ntfy_token": "",
    "whatsapp_telefoon": "",
    "whatsapp_apikey": "",
    "min_bouwjaar": 2022,           # 2022 en nieuwer
    "categorieen": ["personenautos"],
    "meld_opnieuw_geplaatst": True,  # ook oudere advertenties die opnieuw bovenaan gezet zijn
    "interval_minuten": 1,          # alleen voor --loop
    "max_paginas": 15,              # max. resultaatpagina's (12 per pagina) om bij te lezen
    "pauze_tussen_paginas_sec": 2,
}

# Omgevingsvariabelen gaan voor config.json (handig voor GitHub Actions secrets).
ENV_OVERRIDES = {
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "NTFY_TOPIC": "ntfy_topic",
    "NTFY_SERVER": "ntfy_server",
    "NTFY_TOKEN": "ntfy_token",
    "WHATSAPP_TELEFOON": "whatsapp_telefoon",
    "WHATSAPP_APIKEY": "whatsapp_apikey",
    "MIN_BOUWJAAR": "min_bouwjaar",
}

# Netwerkfouten (URLError, time-outs, SSL en verbroken verbindingen zijn allemaal OSError).
NETWERKFOUTEN = (OSError, http.client.HTTPException, EOFError)

log = logging.getLogger("melder")


class WebsiteFout(Exception):
    """schadeautos.nl gaf geen (leesbare) advertenties terug."""


# --------------------------------------------------------------------------- instellingen

def stel_logging_in():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    bestand = logging.handlers.RotatingFileHandler(
        LOG_BESTAND, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    bestand.setFormatter(fmt)
    log.addHandler(bestand)
    # pythonw.exe (onzichtbaar draaien) heeft geen console; dan alleen naar het logbestand.
    if sys.stderr is not None:
        try:
            sys.stderr.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
        scherm = logging.StreamHandler()
        scherm.setFormatter(fmt)
        log.addHandler(scherm)


def lees_config_bestand():
    if not os.path.exists(CONFIG_BESTAND):
        return {}
    with open(CONFIG_BESTAND, encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except ValueError as fout:
            raise SystemExit(f"config.json is ongeldig ({fout}). Herstel het bestand in "
                             "Kladblok, of verwijder het en voer instellen.bat opnieuw uit.")


def bewaar_config(config):
    with open(CONFIG_BESTAND, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def normaliseer_telefoon(nummer):
    nummer = "".join(c for c in str(nummer) if unicodedata.category(c) != "Cf")  # bidi-tekens
    nummer = nummer.replace("(0)", "")
    nummer = re.sub(r"[\s\-().]", "", nummer)
    if nummer.startswith("00"):
        nummer = "+" + nummer[2:]
    elif nummer.startswith("06"):
        nummer = "+31" + nummer[1:]
    elif nummer.startswith("316"):
        nummer = "+" + nummer
    if nummer.startswith("+310"):
        nummer = "+31" + nummer[4:]
    return nummer


def laad_config():
    config = dict(STANDAARD_CONFIG)
    config.update(lees_config_bestand())
    for env, sleutel in ENV_OVERRIDES.items():
        waarde = os.environ.get(env, "").strip()
        if waarde:
            config[sleutel] = waarde
    try:
        config["min_bouwjaar"] = int(config["min_bouwjaar"])
        config["max_paginas"] = max(1, int(config["max_paginas"]))
        config["pauze_tussen_paginas_sec"] = float(config["pauze_tussen_paginas_sec"])
        config["interval_minuten"] = float(config["interval_minuten"])
    except (TypeError, ValueError) as fout:
        raise SystemExit(f"config.json bevat een ongeldige waarde ({fout}).")
    if isinstance(config["categorieen"], str):
        config["categorieen"] = [config["categorieen"]]
    for categorie in config["categorieen"]:
        if categorie not in CATEGORIEEN:
            raise SystemExit(f"Onbekende categorie '{categorie}' in config.json. "
                             f"Kies uit: {', '.join(CATEGORIEEN)}")
    if config["whatsapp_telefoon"]:
        config["whatsapp_telefoon"] = normaliseer_telefoon(config["whatsapp_telefoon"])
        if not re.fullmatch(r"\+\d{8,15}", config["whatsapp_telefoon"]):
            raise SystemExit("whatsapp_telefoon in config.json klopt niet; "
                             "gebruik bijv. +31612345678.")
    return config


def kanalen(config):
    """Namen van de ingestelde meldingskanalen."""
    actief = []
    if config["telegram_bot_token"] and config["telegram_chat_id"]:
        actief.append("Telegram")
    if config["ntfy_topic"]:
        actief.append("ntfy")
    if config["whatsapp_telefoon"] and config["whatsapp_apikey"]:
        actief.append("WhatsApp")
    return actief


# --------------------------------------------------------------------------- status (gezien.json)

def nieuwe_status():
    return {"gezien": [], "gestart": {}, "hoogste_id": 0, "nulmeting_id": 0,
            "vorige_top": {}, "wachtrij": {}, "storing": {}}


def laad_status():
    if not os.path.exists(STATUS_BESTAND):
        return None
    for poging in range(5):
        try:
            with open(STATUS_BESTAND, encoding="utf-8") as f:
                data = json.load(f)
            break
        except ValueError:
            data = None  # kapot bestand: hieronder opnieuw beginnen
            break
        except OSError:
            # Even vergrendeld (virusscanner, back-up): niet meteen alles weggooien.
            if poging == 4:
                raise
            time.sleep(0.5)
    try:
        if data is None:
            raise ValueError("geen geldige JSON")
        status = nieuwe_status()
        status["gezien"] = [str(i) for i in data.get("gezien", [])]
        status["gestart"] = dict(data.get("gestart", {}))
        status["hoogste_id"] = int(data.get("hoogste_id", 0))
        status["nulmeting_id"] = int(data.get("nulmeting_id", 0))
        status["vorige_top"] = {k: [str(i) for i in v]
                                for k, v in data.get("vorige_top", {}).items()}
        status["wachtrij"] = {str(k): v for k, v in data.get("wachtrij", {}).items()
                              if isinstance(v, dict) and "melding" in v}
        status["storing"] = dict(data.get("storing", {}))
        return status
    except (ValueError, TypeError, AttributeError) as fout:
        log.error("Kon %s niet lezen (%s); begin opnieuw met een nulmeting.",
                  STATUS_BESTAND, fout)
        return None


def bewaar_status(status):
    status["gezien"] = status["gezien"][-MAX_ONTHOUDEN:]
    # Eerst naar een tijdelijk bestand schrijven, dan vervangen: nooit een half bestand.
    fd, tijdelijk = tempfile.mkstemp(dir=MAP, prefix=".gezien-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(status, f, indent=0, ensure_ascii=False)
        for poging in range(5):
            try:
                os.replace(tijdelijk, STATUS_BESTAND)
                break
            except PermissionError:
                # Virusscanner of OneDrive heeft het bestand even vast.
                if poging == 4:
                    raise
                time.sleep(0.5)
    except BaseException:
        if os.path.exists(tijdelijk):
            os.remove(tijdelijk)
        raise


class Slot:
    """Voorkomt dat twee melders tegelijk draaien (anders krijg je meldingen dubbel)."""

    def __enter__(self):
        self.bestand = open(SLOT_BESTAND, "a+")
        self.bestand.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.bestand.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.bestand.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.gelukt = True
        except OSError:
            self.gelukt = False
        return self

    def __exit__(self, *_):
        self.bestand.close()  # sluiten geeft het slot ook vrij


# --------------------------------------------------------------------------- website lezen

def haal_op(url, pogingen=3):
    for poging in range(1, pogingen + 1):
        verzoek = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "nl-NL,nl;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(verzoek, timeout=30) as antwoord:
                inhoud = antwoord.read()
                if antwoord.headers.get("Content-Encoding", "").lower() == "gzip":
                    inhoud = gzip.decompress(inhoud)
                return inhoud.decode("utf-8", errors="replace")
        except NETWERKFOUTEN as fout:
            if poging == pogingen:
                raise
            log.warning("Ophalen mislukt (%s), opnieuw proberen...", fout)
            time.sleep(5 * poging)


def _tekst(fragment):
    """HTML-fragment -> platte tekst."""
    if fragment is None:
        return ""
    tekst = re.sub(r"<[^>]+>", " ", fragment)
    tekst = html.unescape(tekst).replace("‑", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", tekst).strip()


def _zoek(patroon, tekst):
    m = re.search(patroon, tekst, re.S | re.I)
    return m.group(1) if m else None


ADVERTENTIE_START = re.compile(
    r'<div\b(?=[^>]*\bclass="[^"]*\bcar\b)[^>]*\bdata-href="(/[^"]*/o/(\d+))"', re.I
)


def lees_advertenties(pagina_html):
    """Haal alle advertenties uit een resultaatpagina."""
    starts = list(ADVERTENTIE_START.finditer(pagina_html))
    advertenties = []
    for i, m in enumerate(starts):
        einde = starts[i + 1].start() if i + 1 < len(starts) else len(pagina_html)
        blok = pagina_html[m.start():einde]
        pad, advertentie_id = m.group(1), m.group(2)

        bouwjaar = _zoek(r'alt="1ste toelating:\s*(\d{4})"', blok)
        prijs = _tekst(_zoek(r'<div class="price">(.*?)</div>', blok))
        if not prijs:
            prijs = _tekst(_zoek(r'<span class="label-price">(.*?)</span>', blok))
        foto = _zoek(r'<div class="car-image[^"]*">.*?<img[^>]*\bsrc="([^"]+)"', blok)

        advertenties.append({
            "id": advertentie_id,
            "url": BASIS_URL + html.unescape(pad),
            "titel": _tekst(_zoek(r"<h2[^>]*>(.*?)</h2>", blok)),
            "type": _tekst(_zoek(r'<p class="model-type">(.*?)</p>', blok)),
            "bouwjaar": int(bouwjaar) if bouwjaar else None,
            "prijs": prijs,
            "brandstof": _tekst(_zoek(r'alt="brandstof:\s*([^"]*)"', blok)),
            "km": _tekst(_zoek(r'alt="tellerstand:\s*([^"]*)"', blok)),
            "foto": urllib.parse.urljoin(BASIS_URL, html.unescape(foto)) if foto else "",
        })
    return advertenties


def zoek_url(categorie, pagina):
    return ZOEK_URL.format(slug=categorie, categorie_id=CATEGORIEEN[categorie], pagina=pagina)


# --------------------------------------------------------------------------- meldingen

def stuur_ntfy(config, melding):
    payload = {
        "topic": config["ntfy_topic"],
        "title": melding["titel"],
        "message": melding["bericht"],
        "tags": [melding.get("tag", "red_car")],
        "priority": 4,
    }
    if melding["link"]:
        payload["click"] = melding["link"]
        payload["actions"] = [{"action": "view", "label": "Bekijk advertentie",
                               "url": melding["link"]}]
    if melding["foto"]:
        payload["attach"] = melding["foto"]
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if config["ntfy_token"]:
        headers["Authorization"] = "Bearer " + config["ntfy_token"]
    verzoek = urllib.request.Request(
        config["ntfy_server"].rstrip("/"), data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    with urllib.request.urlopen(verzoek, timeout=30) as antwoord:
        antwoord.read()


CALLMEBOT_FOUT = re.compile(
    r"\b(error|invalid)\b|too many requests|paused|resume|banned|blocked|not allowed", re.I)


def stuur_whatsapp(config, melding):
    tekst = "{} *{}*\n{}".format(melding.get("emoji", "\U0001F697"), melding["titel"],
                                 melding["bericht"])
    if melding["link"]:
        tekst += "\n" + melding["link"]
    query = urllib.parse.urlencode({
        "phone": config["whatsapp_telefoon"],
        "text": tekst,
        "apikey": config["whatsapp_apikey"],
    })
    verzoek = urllib.request.Request(CALLMEBOT_URL + "?" + query,
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(verzoek, timeout=60) as antwoord:
            code = antwoord.status
            antwoord_tekst = _tekst(antwoord.read().decode("utf-8", errors="replace"))
    finally:
        # Gratis dienst: niet te snel achter elkaar berichten sturen.
        time.sleep(3)
    # CallMeBot herhaalt ons bericht in het antwoord; beoordeel alleen wat erna komt,
    # zodat woorden in de advertentie zelf geen "fout" lijken.
    rest = antwoord_tekst.rpartition(tekst.splitlines()[-1])[2] or antwoord_tekst
    in_wachtrij = re.search(r"message (queued|sent)", rest, re.I)
    if CALLMEBOT_FOUT.search(rest) or (code == 208 and not in_wachtrij):
        hint = ""
        if re.search(r"paused|resume", rest, re.I):
            hint = " (Stuur 'resume' via WhatsApp naar de CallMeBot-bot.)"
        raise RuntimeError("CallMeBot zegt: " + rest[-300:] + hint)
    if not in_wachtrij:
        log.warning("Onverwacht antwoord van CallMeBot: %s", rest[-300:])
    else:
        log.info("CallMeBot: bericht in de wachtrij.")


def _telegram(config, methode, payload):
    url = "{}/bot{}/{}".format(TELEGRAM_API, config["telegram_bot_token"], methode)
    verzoek = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}, method="POST")
    try:
        with urllib.request.urlopen(verzoek, timeout=30) as antwoord:
            data = json.loads(antwoord.read().decode("utf-8"))
    except urllib.error.HTTPError as fout:
        # Telegram legt in de body uit wat er mis is (bijv. "chat not found").
        try:
            uitleg = json.loads(fout.read().decode("utf-8")).get("description", "")
        except (ValueError, OSError):
            uitleg = ""
        raise RuntimeError("Telegram {}: {}".format(fout.code, uitleg or fout.reason)) from None
    if not data.get("ok"):
        raise RuntimeError("Telegram: " + str(data.get("description", data))[:300])
    return data.get("result")


def stuur_telegram(config, melding):
    tekst = "{} <b>{}</b>\n{}".format(melding.get("emoji", "\U0001F697"),
                                      html.escape(melding["titel"]),
                                      html.escape(melding["bericht"]))
    basis = {"chat_id": config["telegram_chat_id"], "parse_mode": "HTML"}
    if melding["link"]:
        tekst += '\n<a href="{}">{}</a>'.format(html.escape(melding["link"], quote=True),
                                                html.escape(melding["link"]))
        basis["reply_markup"] = {"inline_keyboard": [[
            {"text": "Bekijk advertentie", "url": melding["link"]}]]}
    if melding["foto"]:
        try:
            _telegram(config, "sendPhoto", dict(basis, photo=melding["foto"], caption=tekst[:1024]))
            return
        except RuntimeError as fout:
            log.warning("Telegram-foto lukte niet (%s); stuur alleen tekst.", fout)
    _telegram(config, "sendMessage", dict(basis, text=tekst[:4096]))


VERZENDERS = {"Telegram": stuur_telegram, "ntfy": stuur_ntfy, "WhatsApp": stuur_whatsapp}


def verstuur(config, melding, alleen=None, overslaan=()):
    """Stuur naar de ingestelde kanalen (of alleen naar `alleen`).

    Kanalen in `overslaan` lagen deze ronde al plat en worden niet nog eens geprobeerd.
    Geeft (gelukt, mislukt) terug: twee sets met kanaalnamen.
    """
    actief = kanalen(config)
    gelukt, mislukt = set(), set()
    for naam in (alleen if alleen is not None else actief):
        if naam not in actief:
            continue  # kanaal is intussen uitgezet
        if naam in overslaan:
            mislukt.add(naam)
            continue
        try:
            VERZENDERS[naam](config, melding)
            gelukt.add(naam)
        except Exception as fout:  # noqa: BLE001 - nooit de hele run laten crashen op één melding
            log.error("%s-melding mislukt: %s", naam, fout)
            mislukt.add(naam)
    return gelukt, mislukt


def stuur_melding(config, melding):
    """Stuur naar alle ingestelde kanalen. Geeft True als minstens één kanaal lukte."""
    return bool(verstuur(config, melding)[0])


def maak_melding(advertentie, opnieuw_geplaatst=False):
    titel = "{} ({})".format(advertentie["titel"] or "Nieuwe schadeauto", advertentie["bouwjaar"])
    if opnieuw_geplaatst:
        titel = "Opnieuw geplaatst: " + titel
    regels = []
    if advertentie["type"]:
        regels.append(advertentie["type"])
    details = [
        advertentie["prijs"],
        "{} km".format(advertentie["km"]) if advertentie["km"] else "",
        advertentie["brandstof"],
    ]
    regels.append(" · ".join(d for d in details if d))
    return {
        "titel": titel,
        "bericht": "\n".join(r for r in regels if r),
        "link": advertentie["url"],
        "foto": advertentie["foto"],
    }


# --------------------------------------------------------------------------- controle

def _markeer_gezien(status, gezien, advertentie_id):
    if advertentie_id not in gezien:
        gezien.add(advertentie_id)
        status["gezien"].append(advertentie_id)


def _in_wachtrij(status, advertentie_id, melding, kanaal_namen, keer):
    nu = time.time()
    status["wachtrij"][advertentie_id] = {
        "melding": melding, "kanalen": sorted(kanaal_namen), "sinds": nu, "laatst": nu,
        "keer": keer}


def _meld(config, status, gezien, ronde, advertentie_id, melding, later=False):
    """Stuur een melding; kanalen die niet lukken gaan in de wachtrij om later opnieuw te proberen."""
    al_kapot = set(ronde["kapot"])
    gelukt, mislukt = verstuur(config, melding, overslaan=al_kapot)
    ronde["kapot"] |= mislukt
    if gelukt:
        log.info("Gemeld%s via %s: %s %s", " (later)" if later else "",
                 ", ".join(sorted(gelukt)), melding["titel"], melding["link"])
        _markeer_gezien(status, gezien, advertentie_id)
        ronde["verstuurd"] += 1
    if mislukt:
        _in_wachtrij(status, advertentie_id, melding, mislukt,
                     keer=1 if mislukt - al_kapot else 0)
    return bool(gelukt)


def _verwerk_wachtrij(config, status, gezien, ronde):
    """Meldingen die eerder mislukten opnieuw proberen, los van waar de auto nu op de site staat."""
    actief = set(kanalen(config))
    for advertentie_id, item in sorted(list(status["wachtrij"].items()),
                                       key=lambda kv: kv[1].get("sinds", 0)):
        if time.monotonic() - ronde["start"] > VERZEND_BUDGET:
            return
        open_kanalen = [k for k in (item.get("kanalen") or sorted(actief)) if k in actief]
        if not open_kanalen:
            # Dat kanaal is intussen uitgezet: niets meer te doen.
            status["wachtrij"].pop(advertentie_id, None)
            _markeer_gezien(status, gezien, advertentie_id)
            bewaar_status(status)
            continue
        if set(open_kanalen) <= ronde["kapot"]:
            continue  # deze kanalen lukten deze ronde al niet; volgende ronde weer
        al_kapot = set(ronde["kapot"])
        gelukt, mislukt = verstuur(config, item["melding"], alleen=open_kanalen,
                                   overslaan=al_kapot)
        ronde["kapot"] |= mislukt
        if gelukt:
            log.info("Gemeld (later) via %s: %s %s", ", ".join(sorted(gelukt)),
                     item["melding"]["titel"], item["melding"]["link"])
            _markeer_gezien(status, gezien, advertentie_id)
            ronde["verstuurd"] += 1
        if not mislukt:
            status["wachtrij"].pop(advertentie_id, None)
        else:
            item["kanalen"] = sorted(mislukt)
            if mislukt - al_kapot:  # er is echt geprobeerd
                item["keer"] = item.get("keer", 0) + 1
                item["laatst"] = time.time()
            if (item.get("keer", 0) >= MIN_POGINGEN
                    and time.time() - item.get("sinds", 0) > MAX_WACHTTIJD):
                log.error("Melding via %s voor %s lukt na %d pogingen nog steeds niet; "
                          "overgeslagen.", ", ".join(item["kanalen"]),
                          item["melding"]["link"], item["keer"])
                status["wachtrij"].pop(advertentie_id, None)
                _markeer_gezien(status, gezien, advertentie_id)
        bewaar_status(status)


def controleer(config, dry_run=False):
    """Eén controle-ronde. Geeft het aantal verstuurde meldingen terug."""
    status = laad_status()
    eerste_keer = status is None
    if eerste_keer:
        status = nieuwe_status()
    # Gemaakt met een oudere versie (te kleine nulmeting)? Dan één keer stil opnieuw.
    opnieuw_nulmeting = not eerste_keer and status["nulmeting_id"] == 0
    gezien = set(status["gezien"])
    ronde = {"start": time.monotonic(), "verstuurd": 0, "kapot": set()}

    def opslaan():
        if not dry_run:
            bewaar_status(status)

    try:
        if not dry_run:
            _verwerk_wachtrij(config, status, gezien, ronde)

        for nummer, categorie in enumerate(config["categorieen"]):
            if nummer:
                time.sleep(config["pauze_tussen_paginas_sec"])
            # Een categorie die er later bij komt in config.json krijgt ook eerst een nulmeting,
            # anders krijg je in één keer meldingen voor alles wat er al stond.
            nulmeting = eerste_keer or opnieuw_nulmeting or categorie not in status["gestart"]
            vorige_top = set(status["vorige_top"].get(categorie, []))
            top_bereikt = not vorige_top
            nieuwe_top = None
            afgebroken = False
            nieuw_in_categorie = 0
            gelezen = 0
            nieuw_op_pagina = []

            for pagina in range(config["max_paginas"]):
                if pagina:
                    time.sleep(config["pauze_tussen_paginas_sec"])
                advertenties = lees_advertenties(haal_op(zoek_url(categorie, pagina)))
                if not advertenties:
                    if pagina == 0:
                        raise WebsiteFout("geen advertenties gevonden op " + zoek_url(categorie, 0))
                    if not nulmeting:
                        log.warning("%s: pagina %d was leeg; volgende ronde lees ik verder.",
                                    categorie, pagina + 1)
                        afgebroken = True
                    break
                if all(a["bouwjaar"] is None for a in advertenties):
                    raise WebsiteFout("bouwjaar niet te lezen op " + zoek_url(categorie, pagina))
                if dry_run and nulmeting:
                    log.info("[dry-run] %s: eerste keer (nulmeting). De advertenties die er nu "
                             "staan worden onthouden; er gaan nog geen meldingen uit.", categorie)
                    break
                gelezen += len(advertenties)
                if pagina == 0:
                    # Pas opslaan als de hele ronde gelukt is; anders leest de volgende ronde
                    # niet meer door tot waar deze ronde was.
                    nieuwe_top = [a["id"] for a in advertenties]

                # Hoogste ID van vóór deze pagina: daarmee herkennen we opnieuw geplaatste advertenties.
                hoogste_bekend = status["hoogste_id"]
                status["hoogste_id"] = max([hoogste_bekend] + [int(a["id"]) for a in advertenties])

                onbekend = [a for a in advertenties
                            if a["id"] not in gezien and a["id"] not in status["wachtrij"]]
                nieuw_op_pagina = onbekend

                for advertentie in onbekend:
                    advertentie_id = int(advertentie["id"])
                    past = (advertentie["bouwjaar"] or 0) >= config["min_bouwjaar"]
                    opnieuw = bool(hoogste_bekend) and (
                        advertentie_id < hoogste_bekend - OPNIEUW_GEPLAATST_MARGE
                        or (not nulmeting and advertentie_id < status["nulmeting_id"] - 100))
                    if opnieuw and not config["meld_opnieuw_geplaatst"]:
                        past = False

                    if dry_run:
                        if past:
                            melding = maak_melding(advertentie, opnieuw)
                            log.info("[dry-run] zou melden: %s | %s | %s", melding["titel"],
                                     melding["bericht"].replace("\n", " | "), melding["link"])
                        continue
                    if nulmeting or not past:
                        _markeer_gezien(status, gezien, advertentie["id"])
                        continue

                    melding = maak_melding(advertentie, opnieuw)
                    if time.monotonic() - ronde["start"] > VERZEND_BUDGET:
                        # Ronde duurt te lang: volgende ronde versturen.
                        _in_wachtrij(status, advertentie["id"], melding, kanalen(config), keer=0)
                    elif _meld(config, status, gezien, ronde, advertentie["id"], melding):
                        nieuw_in_categorie += 1
                    opslaan()  # meteen vastleggen: nooit twee keer dezelfde melding

                if dry_run and pagina == 0:
                    break
                # Nieuwste staan bovenaan. Bij zijn we als deze pagina niets nieuws had én we
                # in deze ronde de advertenties tegenkwamen die vorige ronde bovenaan stonden.
                # (Alleen opnieuw geplaatste, al bekende advertenties is geen reden om te stoppen.)
                top_bereikt = top_bereikt or any(a["id"] in vorige_top for a in advertenties)
                if not nieuw_op_pagina and not nulmeting and top_bereikt:
                    break
            else:
                if nieuw_op_pagina and not nulmeting and not dry_run:
                    log.warning("%s: ook op pagina %s nog nieuwe advertenties; mogelijk iets "
                                "gemist (laptop lang uit?). Verhoog eventueel max_paginas.",
                                categorie, config["max_paginas"])

            if dry_run:
                continue
            if nieuwe_top and not afgebroken:
                status["vorige_top"][categorie] = nieuwe_top
            if nulmeting and gelezen:
                status["gestart"][categorie] = time.strftime("%Y-%m-%d %H:%M:%S")
                status["nulmeting_id"] = max(status["nulmeting_id"], status["hoogste_id"])
                log.info("Nulmeting %s klaar: %d bestaande advertenties onthouden, "
                         "vanaf nu krijg je meldingen voor nieuwe.", categorie, gelezen)
            elif nieuw_in_categorie == 0 and not status["wachtrij"]:
                log.info("%s: niets nieuws met bouwjaar >= %s.", categorie, config["min_bouwjaar"])
    finally:
        opslaan()
    return ronde["verstuurd"]


# --------------------------------------------------------------------------- storingen

def _meld_storing(config, fout):
    """Houd bij hoe lang de website al niet te lezen is; waarschuw één keer na een half uur."""
    status = laad_status()
    if status is None:
        return
    storing = status["storing"]
    nu = time.time()
    # Draaide de melder een tijd niet (laptop uit), dan telt die tijd niet als storing.
    if not storing.get("sinds") or nu - storing.get("laatst", storing["sinds"]) > 20 * 60:
        storing["sinds"], storing["keer"] = nu, 0
    storing["laatst"] = nu
    storing["keer"] = storing.get("keer", 0) + 1
    if (not storing.get("gemeld") and storing["keer"] >= 3
            and nu - storing["sinds"] > STORING_MELDEN_NA):
        if stuur_melding(config, {
            "titel": "Schadeauto-melder: storing",
            "bericht": "Ik kan schadeautos.nl al {} minuten niet lezen ({}). Je krijgt "
                       "even geen meldingen. Kijk in melder.log.".format(
                           int((time.time() - storing["sinds"]) // 60), str(fout)[:150]),
            "link": "", "foto": "", "tag": "warning", "emoji": "⚠️",
        }):
            storing["gemeld"] = True
    bewaar_status(status)


def _storing_voorbij(config):
    status = laad_status()
    if status is None or not status["storing"]:
        return
    if status["storing"].get("gemeld"):
        stuur_melding(config, {
            "titel": "Schadeauto-melder werkt weer",
            "bericht": "schadeautos.nl is weer te lezen; je krijgt weer meldingen.",
            "link": "", "foto": "", "tag": "white_check_mark", "emoji": "✅",
        })
    status["storing"] = {}
    bewaar_status(status)


def controleer_veilig(config, dry_run=False):
    with Slot() as slot:
        if not slot.gelukt:
            log.info("Er draait al een andere melder; deze ronde overgeslagen.")
            return 0
        try:
            verstuurd = controleer(config, dry_run)
        except (WebsiteFout, *NETWERKFOUTEN) as fout:
            log.error("schadeautos.nl niet te lezen: %s", fout)
            if not dry_run:
                _meld_storing(config, fout)
            raise
        if not dry_run:
            _storing_voorbij(config)
        return verstuurd


# --------------------------------------------------------------------------- instellen

def _vraag(tekst):
    try:
        return input(tekst).strip()
    except EOFError:
        return ""


def _start_config():
    config = dict(STANDAARD_CONFIG)
    config.update(lees_config_bestand())
    return config


def instellen():
    """ntfy instellen: maak een eigen (geheim) kanaal aan en stuur een testmelding."""
    config = _start_config()
    if not config.get("ntfy_topic"):
        config["ntfy_topic"] = "schadeauto-" + secrets.token_urlsafe(12)
        bewaar_config(config)

    print("Meldingen via de gratis ntfy-app")
    print()
    print(" 1. Installeer de app 'ntfy' uit de Play Store (Android) of App Store (iPhone).")
    print(" 2. Open de app, tik op + (Abonneren / Subscribe to topic) en vul deze naam in:")
    print()
    print("        " + config["ntfy_topic"])
    print()
    print("    Laat de server op ntfy.sh staan en tik op Abonneren / Subscribe.")
    print("    Op iPhone: sta meldingen toe als de app daarom vraagt.")
    print()
    print("    Houd deze naam geheim: wie hem kent kan je meldingen lezen.")
    print("    (Hij staat ook in config.json, mocht je hem kwijt zijn.)")
    print()
    _vraag(" 3. Druk hier op Enter als je geabonneerd bent, dan stuur ik een testmelding...")
    return 0 if stuur_testmelding(laad_config()) else 1


def instellen_telegram():
    config = _start_config()
    print("Telegram instellen (gratis, melding met foto en link)")
    print()
    print(" 1. Installeer Telegram op je telefoon en maak een account aan.")
    print(" 2. Zoek in Telegram naar  @BotFather  (met blauw vinkje), tik op Start en stuur:")
    print("        /newbot")
    print("    Kies een naam (bijv. Schadeauto Melder) en daarna een gebruikersnaam")
    print("    die eindigt op 'bot' (bijv. schadeauto_yassine_bot).")
    print(" 3. BotFather stuurt je een token, zoiets als  123456789:AAHk3...")
    print("    Kopieer dat token naar je pc, bijvoorbeeld via https://web.telegram.org")
    print("    (inloggen met de QR-code) of door het naar jezelf te mailen.")
    print()
    token = re.sub(r"\s", "", _vraag("Plak hier het token: "))
    if not re.fullmatch(r"\d{5,}:[\w-]{30,}", token):
        print("Dat lijkt geen geldig token. Voer instellen-telegram.bat opnieuw uit.")
        return 1
    config["telegram_bot_token"] = token
    try:
        bot = _telegram(config, "getMe", {})
    except (RuntimeError, *NETWERKFOUTEN) as fout:
        print("Telegram accepteert dit token niet ({}). Klopt het?".format(fout))
        return 1
    bewaar_config(config)  # token alvast bewaren, ook als de volgende stap misgaat
    naam = bot.get("username", "")
    print()
    print(" 4. Open nu je bot in Telegram: https://t.me/" + naam)
    print("    Tik op Start (of stuur 'hallo').")
    _vraag("    Druk daarna hier op Enter...")

    chat_id = ""
    for poging in range(4):
        try:
            for update in reversed(_telegram(config, "getUpdates", {}) or []):
                bericht = update.get("message") or update.get("my_chat_member") or {}
                if bericht.get("chat", {}).get("id"):
                    chat_id = str(bericht["chat"]["id"])
                    break
        except (RuntimeError, *NETWERKFOUTEN) as fout:
            print("Kon Telegram niet bereiken ({}).".format(fout))
        if chat_id or poging == 3:
            break
        _vraag("    Nog geen bericht gezien. Tik op Start / stuur 'hallo' naar @{} "
               "en druk op Enter...".format(naam))
    if not chat_id:
        print("Geen bericht van je ontvangen. Voer instellen-telegram.bat opnieuw uit.")
        return 1
    config["telegram_chat_id"] = chat_id

    if config.get("ntfy_topic"):
        antwoord = _vraag("\nntfy uitzetten? Op je iPhone gaf ntfy geen melding. [J/n]: ").lower()
        if antwoord in ("", "j", "ja", "y", "yes"):
            config["ntfy_topic"] = ""
    bewaar_config(config)
    print()
    print("Opgeslagen in config.json (voor GitHub: TELEGRAM_CHAT_ID = {}).".format(chat_id))
    print("Ik stuur nu een testmelding...")
    return 0 if stuur_testmelding(laad_config()) else 1


def instellen_whatsapp():
    config = _start_config()
    print("WhatsApp instellen (via CallMeBot, gratis voor persoonlijk gebruik)")
    print()
    print(" 1. Open deze pagina en kijk welk telefoonnummer de CallMeBot-bot nu heeft:")
    print("    " + CALLMEBOT_UITLEG)
    print(" 2. Sla dat nummer op (met +34 ervoor) en stuur het via WhatsApp precies dit bericht:")
    print("    I allow callmebot to send me messages")
    print(" 3. Binnen een paar minuten krijg je een bericht terug met je 'apikey'.")
    print()
    telefoon = normaliseer_telefoon(_vraag("Jouw WhatsApp-nummer (bijv. 0612345678): "))
    if not re.fullmatch(r"\+\d{8,15}", telefoon):
        print("Dat nummer klopt niet. Gebruik bijv. 0612345678 of +31612345678.")
        return 1
    print("Nummer: " + telefoon)
    apikey = _vraag("De apikey die je van CallMeBot kreeg: ")
    if not apikey:
        print("Geen apikey ingevuld, er is niets opgeslagen.")
        return 1
    config["whatsapp_telefoon"], config["whatsapp_apikey"] = telefoon, apikey
    bewaar_config(config)
    print()
    print("Opgeslagen in config.json. Ik stuur nu een testmelding...")
    return 0 if stuur_testmelding(laad_config()) else 1


def stuur_testmelding(config):
    gelukt, mislukt = verstuur(config, {
        "titel": "Schadeauto-melder werkt!",
        "bericht": "Je krijgt een melding bij nieuwe auto's op schadeautos.nl "
                   "vanaf bouwjaar {}.".format(config["min_bouwjaar"]),
        "link": BASIS_URL,
        "foto": "",
    })
    if gelukt:
        log.info("Testmelding verstuurd via %s. Kijk op je telefoon "
                 "(WhatsApp kan een paar minuten duren).", ", ".join(sorted(gelukt)))
    if mislukt:
        log.error("Testmelding MISLUKT via %s, zie de fout hierboven.", ", ".join(sorted(mislukt)))
    return bool(gelukt) and not mislukt


# --------------------------------------------------------------------------- start

def main():
    parser = argparse.ArgumentParser(description="Meldingen voor nieuwe schadeauto's.")
    parser.add_argument("--instellen", action="store_true", help="ntfy-app instellen")
    parser.add_argument("--instellen-whatsapp", action="store_true",
                        help="WhatsApp via CallMeBot instellen")
    parser.add_argument("--instellen-telegram", action="store_true",
                        help="Telegram instellen")
    parser.add_argument("--test", action="store_true", help="stuur een testmelding")
    parser.add_argument("--loop", action="store_true", help="blijf controleren")
    parser.add_argument("--dry-run", action="store_true",
                        help="niets versturen of opslaan, alleen tonen")
    args = parser.parse_args()

    stel_logging_in()

    try:
        if args.instellen:
            sys.exit(instellen())
        if args.instellen_whatsapp:
            sys.exit(instellen_whatsapp())
        if args.instellen_telegram:
            sys.exit(instellen_telegram())
        config = laad_config()
        if not args.dry_run and not kanalen(config):
            raise SystemExit("Nog niets ingesteld. Voer eerst instellen-telegram.bat, "
                             "instellen.bat of instellen-whatsapp.bat uit.")
    except SystemExit as stop:
        # Ook in het logboek zetten: op de achtergrond (pythonw) is er geen scherm.
        if isinstance(stop.code, str):
            log.error(stop.code)
        raise

    if args.test:
        sys.exit(0 if stuur_testmelding(config) else 1)

    if not args.loop:
        try:
            controleer_veilig(config, args.dry_run)
        except Exception as fout:  # noqa: BLE001
            if not isinstance(fout, (WebsiteFout, *NETWERKFOUTEN)):
                log.exception("Controle mislukt")
            sys.exit(1)
        # Blijft een melding steeds mislukken, eindig dan met een fout: op GitHub wordt de
        # run dan rood en krijg je een e-mail. (De Windows-taak negeert dit.)
        status = laad_status() or nieuwe_status()
        vast = [i for i in status["wachtrij"].values() if i.get("keer", 0) >= 3]
        if vast and not args.dry_run:
            log.error("%d melding(en) lukken al een paar keer niet via %s.", len(vast),
                      ", ".join(sorted({k for i in vast for k in i.get("kanalen", [])})))
            sys.exit(1)
        return

    log.info("Melder gestart: elke %s minuut controleren (Ctrl+C om te stoppen).",
             config["interval_minuten"])
    while True:
        try:
            config = laad_config()  # wijzigingen in config.json gelden meteen
        except SystemExit as stop:
            log.error("%s (de vorige instellingen blijven gelden)", stop.code)
        try:
            controleer_veilig(config, args.dry_run)
        except Exception as fout:  # noqa: BLE001 - in de loop doorgaan na een fout
            if not isinstance(fout, (WebsiteFout, *NETWERKFOUTEN)):
                log.exception("Controle mislukt, volgende keer opnieuw")
        time.sleep(max(30.0, config["interval_minuten"] * 60))


if __name__ == "__main__":
    main()

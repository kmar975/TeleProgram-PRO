"""
Moduł zaawansowanego algorytmu rankingowego filmów (Indeks Jakości 0-100 pkt).
Zawiera:
- Hierarchię prestiżu nagród (Tier List: Poziom S, A, B, C oraz ujemny za Złote Maliny)
- Rozróżnienie między wygraną a nominacją (100% vs 35% wagi)
- Mnożnik za liczbę statuetek z malejącą korzyścią
- Premię za kategorię główną (Najlepszy Film / Reżyseria)
- Średnią ważoną Bayesa (Weighted Rating wg wzoru IMDb)
- Bonus za nowości (2024-2026), klasyki oraz kanały bez reklam
- Trwały dyskowy cache (movies_cache.json) oraz obsługę OMDb / TMDB API.
"""

import json
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "movies_cache.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_config.json")

# Kanały nadające filmy bez przerw reklamowych
AD_FREE_CHANNELS = {
    "HBO", "HBO 2", "CANAL+ Premium", "CANAL+ Film", "CANAL+ 1", "CANAL+ 4K",
    "Ale kino+", "TVP Kultura", "TVP Historia", "TVP Dokument", "TVP Nauka"
}

# Słownik liczb słownych używanych w opisach telewizyjnych
WORD_NUMBERS = {
    "dwoma": 2, "dwa": 2, "dwóch": 2, "dwie": 2,
    "trzema": 3, "trzy": 3, "trzech": 3,
    "czterema": 4, "cztery": 4, "czterech": 4,
    "pięcioma": 5, "pięć": 5, "pięciu": 5,
    "sześcioma": 6, "sześć": 6, "sześciu": 6,
    "siedmioma": 7, "siedem": 7, "siedmiu": 7,
    "ośmioma": 8, "osiem": 8, "ośmiu": 8,
    "dziewięcioma": 9, "dziewięć": 9, "dziewięciu": 9,
    "dziesięcioma": 10, "dziesięć": 10, "dziesięciu": 10,
    "jedenastoma": 11, "jedenaście": 11, "jedenastu": 11,
    "dwunastoma": 12, "dwanaście": 12, "dwunastu": 12,
}


class WeightedAwardsCalculator:
    """Zaawansowany kalkulator hierarchii nagród filmowych (Tier List)."""

    AWARD_TIERS = [
        # Poziom S: Najwyższy światowy prestiż (Oscar, Cannes, Wenecja, Berlin)
        {
            "name": "Oscar",
            "win_weight": 10.0,
            "nom_weight": 3.5,
            "extra_per_item": 1.5,
            "badge_win": "🏆 Oscar",
            "badge_nom": "✨ Nom. do Oscara",
            "pattern": r"(\b(?:oscar|oskar)(?:[aey]|em|owi|ze|ów|om|ami|ach|s)?\b|\bnagrod[a-ząćęłńóśźż]* akademii\b)",
        },
        {
            "name": "Cannes / Wenecja / Berlin",
            "win_weight": 9.5,
            "nom_weight": 3.0,
            "extra_per_item": 1.0,
            "badge_win": "🌴 Złota Palma / Lew / Niedźwiedź",
            "badge_nom": "✨ Konkurs główny (Cannes/Wenecja/Berlin)",
            "pattern": r"(\bzłot[a-ząćęłńóśźż]* palm[a-ząćęłńóśźż]*\b|\bpalme d'or\b|(?:festiwal[a-ząćęłńóśźż]*|nagrod[a-ząćęłńóśźż]*|laur[a-ząćęłńóśźż]*|konkurs[a-ząćęłńóśźż]*|grand prix|wyróżnion[a-ząćęłńóśźż]*)\s+(?:[a-ząćęłńóśźż]+\s+){0,3}(?:w\s+)?cannes\b|cannes\s+(?:film\s+)?festival\b|\bzłot[a-ząćęłńóśźż]* (?:lw[a-ząćęłńóśźż]*|niedźwiedzi[a-ząćęłńóśźż]*)\b|\bberlinale\b|\bfestiwal[u]? w wenecji\b)",
        },
        # Poziom A: Wysoki prestiż międzynarodowy (Złoty Glob, BAFTA, Cezar, EFA)
        {
            "name": "Złoty Glob",
            "win_weight": 6.0,
            "nom_weight": 2.0,
            "extra_per_item": 1.0,
            "badge_win": "🌐 Złoty Glob",
            "badge_nom": "✨ Nom. Złoty Glob",
            "pattern": r"(\bzłot[a-ząćęłńóśźż]* glob[a-ząćęłńóśźż]*\b|\bgolden globe[s]?\b)",
        },
        {
            "name": "BAFTA / Cezar / EFA",
            "win_weight": 5.5,
            "nom_weight": 2.0,
            "extra_per_item": 0.8,
            "badge_win": "🎭 BAFTA / Cezar / EFA",
            "badge_nom": "✨ Nom. BAFTA / Cezar",
            "pattern": r"(\bbafta\b|\bcezar[aeyówem]*\b|\beuropejsk[a-ząćęłńóśźż]* nagrod[a-ząćęłńóśźż]* filmow[a-ząćęłńóśźż]*\b)",
        },
        # Poziom B: Najważniejsze nagrody polskie (Orły, Złote Lwy Gdynia) - ratuje polskie kino
        {
            "name": "Orły / Złote Lwy (Polska)",
            "win_weight": 6.0,
            "nom_weight": 2.0,
            "extra_per_item": 1.0,
            "badge_win": "🦅 Orzeł / Złote Lwy",
            "badge_nom": "✨ Nom. Orły",
            "pattern": r"(\bpolsk[a-ząćęłńóśźż]* nagrod[a-ząćęłńóśźż]* filmow[a-ząćęłńóśźż]*\b|\bpolski[a-ząćęłńóśźż]* orł[a-ząćęłńóśźż]*\b|\b(?:nagrodzon[a-ząćęłńóśźż]*|zdobywc[a-ząćęłńóśźż]*|laureat[a-ząćęłńóśźż]*|nominacj[a-ząćęłńóśźż]*|nominow[a-ząćęłńóśźż]*)\s+(?:[a-ząćęłńóśźż0-9]+\s+){0,3}orł[a-ząćęłńóśźż]*\b|\bfestiwal[a-ząćęłńóśźż]* w gdyni\b|\bzłot[a-ząćęłńóśźż]* lwy\b|\bfestiwal[a-ząćęłńóśźż]* polskich filmów\b)",
        },
        # Poziom C: Nagrody gatunkowe i festiwale kina niezależnego
        {
            "name": "Sundance / Saturn",
            "win_weight": 3.5,
            "nom_weight": 1.0,
            "extra_per_item": 0.5,
            "badge_win": "🏅 Sundance / Saturn",
            "badge_nom": "✨ Nom. Saturn",
            "pattern": r"(\bsundance\b|\bsaturn[aeyów]*\b|\bemmy\b)",
        },
    ]

    @classmethod
    def clean_person_awards(cls, text: str) -> str:
        """
        Wyklucza wzmianki o nagrodach i nominacjach przypisanych do osób (reżyserów, aktorów, twórców),
        tak aby nie były błędnie przypisywane bieżącemu filmowi (np. 'w reżyserii wyróżnionego Oscarem',
        'Laureaci Oscara X i Y powracają na ekran').
        """
        if not text:
            return ""
        # 1. 'w reżyserii' / 'z udziałem' / 'w rolach głównych' + laureata/nagrodzonego Oscara
        p1 = (
            r"(?:w\s+reżyserii|z\s+udziałem|w\s+rolach\s+głównych)\s+"
            r"(?:wyróżnion[a-ząćęłńóśźż]*|nagrodzon[a-ząćęłńóśźż]*|zdobywc[a-ząćęłńóśźż]*|laureat[a-ząćęłńóśźż]*|laureac[a-ząćęłńóśźż]*)\s+"
            r"(?:oscar[a-ząćęłńóśźż]*|oskar[a-ząćęłńóśźż]*|nagrod[a-ząćęłńóśźż]*\s+akademii)"
        )
        text = re.sub(p1, " ", text, flags=re.IGNORECASE)

        # 2. reżyser / twórca / aktor / aktorka / gwiazda + nagrodzony Oscarem
        p2 = (
            r"(?:reżyser(?:a|em|zy|ze)?|twórc[a-ząćęłńóśźż]*|aktor(?:a|em|zy|ka|ki|kę|ką)?|gwiazd[a-ząćęłńóśźż]*)\s+"
            r"(?:wyróżnion[a-ząćęłńóśźż]*|nagrodzon[a-ząćęłńóśźż]*|zdobywc[a-ząćęłńóśźż]*|laureat[a-ząćęłńóśźż]*|laureac[a-ząćęłńóśźż]*)\s+"
            r"(?:oscar[a-ząćęłńóśźż]*|oskar[a-ząćęłńóśźż]*)"
        )
        text = re.sub(p2, " ", text, flags=re.IGNORECASE)

        # 3. Laureaci / zdobywcy / wyróżnieni Oscarem + WIELKA LITERA (Imię i Nazwisko)
        p3 = (
            r"(?i:(?:laureat[a-ząćęłńóśźż]*|laureac[a-ząćęłńóśźż]*|zdobywc[a-ząćęłńóśźż]*|wyróżnion[a-ząćęłńóśźż]*|nagrodzon[a-ząćęłńóśźż]*)\s+"
            r"(?:oscar[a-ząćęłńóśźż]*|oskar[a-ząćęłńóśźż]*|nagrod[a-ząćęłńóśźż]*\s+akademii))"
            r"(?:\s+(?:i\s+|oraz\s+)?[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+){1,3}"
        )
        text = re.sub(p3, " ", text)
        return text

    @classmethod
    def evaluate_awards(cls, polish_desc: str = "", omdb_awards: str = "") -> Tuple[float, str]:
        """
        Oblicza ważone punkty za nagrody (od -6.0 do +20.0 pkt) oraz zwraca sformatowane odznaki.
        """
        cleaned_desc = cls.clean_person_awards(polish_desc)
        text = f"{cleaned_desc} {omdb_awards}".lower()
        total_points = 0.0
        badges = []

        # 1. Poziom Ujemny: Antynagrody (Złote Maliny / Węże)
        if re.search(r"(złot[a-ząćęłńóśźż]*\s+malin[a-ząćęłńóśźż]*|razzie|węż[a-ząćęłńóśźż]*|antynagrod[a-ząćęłńóśźż]*)", text):
            total_points -= 6.0
            badges.append("🍓 Złota Malina")

        # 2. Sprawdzenie koszyków nagród (Tier S, A, B, C)
        for tier in cls.AWARD_TIERS:
            pat = tier["pattern"]
            if re.search(pat, text):
                # Sprawdzenie, czy wzmianka dotyczy samej nominacji (np. "nominacja do Oscara", "nominowany do 3 Oscarów")
                is_only_nomination = bool(
                    re.search(rf"(?:nominacj[a-ząćęłńóśźż]*|nominow[a-ząćęłńóśźż]*|nominat[a-z]*|nominee[a-z]*)\s+(?:do\s+)?(?:[a-ząćęłńóśźż0-9]+\s+){{0,3}}{pat}", text)
                    or re.search(rf"{pat}\s+nominee[a-z]*", text)
                )

                # Jeżeli w bezpośrednim sąsiedztwie jest wyraźnie "nagrodzony" lub "zdobywca", wygrana ma pierwszeństwo
                has_win_verb = bool(
                    re.search(rf"(?:nagrodzon[a-ząćęłńóśźż]*|zdobywc[a-ząćęłńóśźż]*|laureat[a-ząćęłńóśźż]*|won)\s+(?:[a-ząćęłńóśźż0-9]+\s+){{0,3}}{pat}", text)
                )
                if is_only_nomination and has_win_verb:
                    is_only_nomination = False

                # Wykrywanie liczby statuetek (liczby arabskie lub słownie tuż przed nagrodą)
                count = 1
                num_match = (
                    re.search(rf"(\d+)\s+(?:statuetk[a-ząćęłńóśźż]*\s+)?(?:nagrod[a-ząćęłńóśźż]*\s+)?{pat}", text)
                    or re.search(rf"won\s+(\d+)\s+{pat}", text)
                    or re.search(rf"nominated for\s+(\d+)\s+{pat}", text)
                )
                if num_match:
                    count = int(num_match.group(1))
                else:
                    for word_num, val in WORD_NUMBERS.items():
                        if re.search(rf"\b{word_num}\b\s+(?:statuetk[a-ząćęłńóśźż]*\s+)?(?:nagrod[a-ząćęłńóśźż]*\s+)?(?:do\s+)?{pat}", text):
                            count = val
                            break

                if is_only_nomination:
                    # Nominacja ma 35% wagi wygranej
                    pts = tier["nom_weight"] + (count - 1) * (tier["extra_per_item"] * 0.4)
                    total_points += pts
                    badges.append(f"{tier['badge_nom']}" + (f" ({count})" if count > 1 else ""))
                else:
                    # Wygrana z malejącą korzyścią za kolejne statuetki
                    pts = tier["win_weight"] + (count - 1) * tier["extra_per_item"]
                    total_points += pts
                    badges.append(f"{tier['badge_win']}" + (f" ({count})" if count > 1 else ""))

        # 3. Premia za kategorię główną (Najlepszy Film / Reżyseria)
        if total_points > 0 and re.search(r"(najlepszy film|najlepsz[aą] reżyseri[aę]|najlepszy reżyser|best picture|best director)", text):
            total_points += 3.0
            badges.append("👑 Główna Kategoria")

        # Limit nasycenia nagród: od -6.0 do +20.0 pkt
        final_bonus = max(-6.0, min(20.0, round(total_points, 1)))
        badges_str = " | ".join(badges) if badges else "—"
        return final_bonus, badges_str


def clean_movie_title(raw: str) -> str:
    """
    Oczyszcza tytuł z prefiksów pasm telewizyjnych i cykli filmowych przed dwukropkiem oraz oznaczeń odcinków.
    Rozpoznaje popularne cykle: 'Wieczór kinomana:', 'Bilet do kina:', 'Kino nocne:', 'Hit na sobotę:',
    'Klasyka kina:', 'Zakochana Jedynka:', 'Gwiazdy w południe:', 'Mocne sobotnie kino:', 'Niedziela z...:',
    'Czwartkowy klub filmowy:', 'Premiera:', 'Hit dnia:', 'Pasmo filmowe:' itp.
    """
    if not raw:
        return ""
    # Rozbudowany regex odcinający wszystkie popularne cykle TV przed dwukropkiem
    t = re.sub(
        r"^(?:"
        r"wiecz[oó]r\s+kinomana|"
        r"bilet\s+do\s+kina|"
        r"kino\s+(?:nocne|relaks|konesera|bez\s+granic|mocne|kultowe)|"
        r"mocne\s+sobotnie\s+kino|"
        r"hit\s+(?:na\s+sobot[eę]|dnia)|"
        r"megahit|"
        r"klasyka\s+kina|"
        r"zakochana\s+jedynka|"
        r"gwiazdy\s+w\s+po[lł]udnie|"
        r"niedziela\s+z(?:e)?\s+[^:]+|"
        r"(?:czwartkowy|czartoryski|wtorkowy|pi[aą]tkowy|sobotni|niedzielny)?\s*klub\s+filmowy|"
        r"pasmo\s+filmowe|"
        r"okruchy\s+losu|"
        r"studio\s+filmowe|"
        r"retro\s+kino|"
        r"noc\s+kr[oó]tkich\s+film[oó]w|"
        r"dokument\s+tygodnia|"
        r"natura\s+w\s+jedynce|"
        r"nocny\s+dokument|"
        r"premiera"
        r"):\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    # Odcięcie numeracji odcinków i części na końcu tytułu
    t = re.sub(r"\s*\(\d+(?:/\d+)?\)\s*$", "", t)
    t = re.sub(r"\s*cz(?:\.|ęść)?\s*\d+\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def normalize_title(title: str) -> str:
    """
    Normalizuje tytuł do klucza cache/bazy wiedzy.
    Najpierw wywołuje clean_movie_title(), następnie usuwa nawiasy, znaki specjalne i polskie diakrytyki.
    """
    t = clean_movie_title(title).lower()
    t = re.sub(r"\s*\([^)]*\)", "", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = " ".join(t.split())
    replacements = {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
    for k, v in replacements.items():
        t = t.replace(k, v)
    return t


def titles_match(query: str, candidate: str) -> bool:
    """Inteligentne porównanie tytułów zapobiegające fałszywym dopasowaniom z API wyszukiwarki."""
    if not query or not candidate:
        return False
    q = re.sub(r"[^\w\s]", "", query.lower()).strip()
    c = re.sub(r"[^\w\s]", "", candidate.lower()).strip()
    if q == c:
        return True
    if q in c or c in q:
        q_words = set(q.split())
        c_words = set(c.split())
        common = q_words & c_words
        if len(common) >= 1 and any(len(w) >= 4 for w in common):
            ratio = len(common) / max(len(q_words), 1)
            if ratio >= 0.5 or (len(q_words) >= 2 and len(common) >= 2):
                return True
    return False


# Baza startowa znanych filmów z dokładnymi ocenami i głosami z IMDb/Filmwebu
RAW_BUILTIN: Dict[str, dict] = {
    "skazani na shawshank": {"rating": 9.3, "votes": 2900000, "year": 1994, "awards": "Nominated for 7 Oscars. Another 21 wins & 43 nominations."},
    "ojciec chrzestny": {"rating": 9.2, "votes": 2000000, "year": 1972, "awards": "Won 3 Oscars, including Best Picture. Another 31 wins & 30 nominations."},
    "mroczny rycerz": {"rating": 9.0, "votes": 2800000, "year": 2008, "awards": "Won 2 Oscars. Another 163 wins & 164 nominations."},
    "dwunastu gniewnych ludzi": {"rating": 9.0, "votes": 850000, "year": 1957, "awards": "Nominated for 3 Oscars, including Best Picture."},
    "lista schindlera": {"rating": 9.0, "votes": 1400000, "year": 1993, "awards": "Won 7 Oscars, including Best Picture and Best Director."},
    "władca pierścieni: powrót króla": {"rating": 9.0, "votes": 1950000, "year": 2003, "awards": "Won 11 Oscars, including Best Picture."},
    "pulp fiction": {"rating": 8.9, "votes": 2200000, "year": 1994, "awards": "Won 1 Oscar. Złota Palma Cannes 1994."},
    "dobry, zły i brzydki": {"rating": 8.8, "votes": 800000, "year": 1966, "awards": "Klasyk westernu."},
    "forrest gump": {"rating": 8.8, "votes": 2250000, "year": 1994, "awards": "Won 6 Oscars, including Best Picture and Best Actor."},
    "fight club": {"rating": 8.8, "votes": 2300000, "year": 1999, "awards": "Nominated for 1 Oscar."},
    "incepcja": {"rating": 8.8, "votes": 2550000, "year": 2010, "awards": "Won 4 Oscars. Another 159 wins."},
    "matrix": {"rating": 8.7, "votes": 2050000, "year": 1999, "awards": "Won 4 Oscars."},
    "chłopcy z ferajny": {"rating": 8.7, "votes": 1250000, "year": 1990, "awards": "Won 1 Oscar. BAFTA Best Film."},
    "interstellar": {"rating": 8.7, "votes": 2100000, "year": 2014, "awards": "Won 1 Oscar. Saturn Best Sci-Fi."},
    "zielona mila": {"rating": 8.6, "votes": 1400000, "year": 1999, "awards": "Nominated for 4 Oscars, including Best Picture."},
    "milczenie owiec": {"rating": 8.6, "votes": 1550000, "year": 1991, "awards": "Won 5 Oscars, including Best Picture and Best Director."},
    "gladiator": {"rating": 8.5, "votes": 1600000, "year": 2000, "awards": "Won 5 Oscars, including Best Picture."},
    "leon zawodowiec": {"rating": 8.5, "votes": 1200000, "year": 1994, "awards": "Cezar Best Film nomination."},
    "pianista": {"rating": 8.5, "votes": 900000, "year": 2002, "awards": "Won 3 Oscars, including Best Director. Złota Palma Cannes."},
    "diuna: część druga": {"rating": 8.5, "votes": 520000, "year": 2024, "awards": "Won 2 Oscars. BAFTA Best Sound."},
    "diuna": {"rating": 8.0, "votes": 750000, "year": 2021, "awards": "Won 6 Oscars."},
    "oppenheimer": {"rating": 8.8, "votes": 760000, "year": 2023, "awards": "Won 7 Oscars, including Best Picture and Best Director. 5 Złotych Globów."},
    "boże ciało": {"rating": 7.7, "votes": 40000, "year": 2019, "awards": "Nominowany do Oscara za najlepszy film międzynarodowy, 11 Polskich Orłów."},
    "kler": {"rating": 7.1, "votes": 35000, "year": 2018, "awards": "Złote Lwy Festiwal w Gdyni, nagrodzony Polskimi Orłami."},
    "bogowie": {"rating": 7.8, "votes": 55000, "year": 2014, "awards": "Złote Lwy Festiwal w Gdyni, 7 Polskich Orłów."},
    "kos": {"rating": 7.3, "votes": 18000, "year": 2023, "awards": "Złote Lwy na Festiwalu w Gdyni, 6 Polskich Orłów."},
    "zimna wojna": {"rating": 7.5, "votes": 65000, "year": 2018, "awards": "Cannes Najlepsza Reżyseria, 3 nominacje do Oscara, 7 Orłów."},
    "vinci": {"rating": 7.4, "votes": 48000, "year": 2004, "awards": "Festiwal Polskich Filmów Fabularnych w Gdyni."},
    "vinci 2": {"rating": 5.8, "votes": 8500, "year": 2025, "awards": "Polska premiera kinowa 2025."},
    "bullet train": {"rating": 7.3, "votes": 410000, "year": 2022, "awards": ""},
    "taxi 2": {"rating": 6.5, "votes": 95000, "year": 2000, "awards": ""},
    "straszny film 4": {"rating": 5.1, "votes": 130000, "year": 2006, "awards": ""},
    "air america": {"rating": 5.8, "votes": 32000, "year": 1990, "awards": ""},
    "czas wojny": {"rating": 7.2, "votes": 160000, "year": 2011, "awards": "6 nominacji do Oscara."},
    "sprzymierzeni": {"rating": 7.1, "votes": 175000, "year": 2016, "awards": "Nominacja do Oscara za kostiumy."},
    "lokatorka": {"rating": 6.0, "votes": 4500, "year": 2021, "awards": "Złote Lwy Gdynia za rolę drugoplanową."},
    "na twoim miejscu": {"rating": 5.9, "votes": 6000, "year": 2023, "awards": ""},
    "król życia": {"rating": 5.5, "votes": 8500, "year": 2015, "awards": ""},
    "lot skazańców": {"rating": 6.9, "votes": 350000, "year": 1997, "awards": "2 nominacje do Oscara."},
    "anatomia upadku": {"rating": 7.7, "votes": 165000, "year": 2023, "awards": "Won 1 Oscar. Złota Palma Cannes 2023."},
    "strefa interesów": {"rating": 7.5, "votes": 140000, "year": 2023, "awards": "Won 2 Oscars, including Best International Film. Grand Prix Cannes."},
    "terminator: mroczne przeznaczenie": {"rating": 6.2, "votes": 190000, "year": 2019, "awards": "Film SF."},
    "transporter 3": {"rating": 6.1, "votes": 180000, "year": 2008, "awards": "Film akcji."},
    "bez twarzy": {"rating": 7.3, "votes": 400000, "year": 1997, "awards": "Nominated for 1 Oscar."},
    "czas zemsty": {"rating": 5.2, "votes": 25000, "year": 2003, "awards": "Film sensacyjny."},
    "mumia: grobowiec cesarza smoka": {"rating": 5.2, "votes": 175000, "year": 2008, "awards": "Film przygodowy."},
    "poszukiwany, poszukiwana": {"rating": 7.6, "votes": 35000, "year": 1972, "awards": "Kultowa polska komedia Stanisława Barei."},
    "sami swoi": {"rating": 8.1, "votes": 60000, "year": 1967, "awards": "Złota Kaczka. Klasyk polskiej komedii."},
    "znachor": {"rating": 7.8, "votes": 45000, "year": 1981, "awards": "Klasyk polskiego kina."},
    "chłopi": {"rating": 7.6, "votes": 28000, "year": 2023, "awards": "Polski kandydat do Oscara. 4 Polskie Orły."},
    "transformers: zemsta upadłych": {"rating": 5.9, "votes": 420000, "year": 2009, "awards": "Nominacja do Oscara za dźwięk, ale także trzy Złote Maliny."},
}

# Wszystkie klucze słownika są znormalizowane funkcją normalize_title
BUILTIN_KNOWLEDGE: Dict[str, dict] = {normalize_title(k): v for k, v in RAW_BUILTIN.items()}


class MovieRanker:
    def __init__(self):
        self.cache: Dict[str, dict] = self._load_cache()
        self.config: dict = self._load_config()

    def _load_cache(self) -> Dict[str, dict]:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Ranker] Błąd ładowania cache: {e}")
        return {}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Ranker] Błąd zapisu cache: {e}")

    def _load_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"omdb_api_key": "", "tmdb_api_key": ""}

    def save_api_keys(self, omdb_key: str = "", tmdb_key: str = ""):
        self.config["omdb_api_key"] = omdb_key.strip()
        self.config["tmdb_api_key"] = tmdb_key.strip()
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"[Ranker] Błąd zapisu kluczy API: {e}")

    @staticmethod
    def extract_year(genre_str: str) -> Optional[int]:
        if not genre_str:
            return None
        match = re.search(r"\b(19\d{2}|20\d{2})\b", genre_str)
        return int(match.group(1)) if match else None

    @staticmethod
    def format_votes(votes: int) -> str:
        if not votes or votes <= 0:
            return ""
        if votes >= 1_000_000:
            val = votes / 1_000_000
            return f"{val:.1f}M"
        if votes >= 1_000:
            val = round(votes / 1_000)
            return f"{int(val)}k"
        return str(votes)

    @classmethod
    def calculate_score(
        cls,
        rating: float = 0.0,
        votes: int = 0,
        year: Optional[int] = None,
        awards_str: str = "",
        desc: str = "",
        channel: str = "",
        current_year: int = 2026,
    ) -> dict:
        """
        Wylicza ostateczny Indeks Jakości (0-100 pkt) łącząc średnią ważoną Bayesa,
        wielopoziomowy kalkulator nagród (Tier List) oraz premie za wiek i stację.
        """
        # Średnia ważona Bayesa
        m = 3000.0
        C = 6.0

        if rating > 0:
            if votes > 0:
                weighted_rating = (votes / (votes + m)) * rating + (m / (votes + m)) * C
            else:
                weighted_rating = 0.70 * rating + 0.30 * C
            # Bazowa składowa z ocen (maks. ~78 pkt przy ocenie 10/10)
            base_points = weighted_rating * 7.8
        else:
            weighted_rating = 0.0
            base_points = 28.0  # Neutralny bazowy pułap dla produkcji bez ocen (brak danych)

        # Zaawansowana hierarchia nagród (od -6.0 do +20.0 pkt) - TYLKO PRAWDZIWE NAGRODY FILMOWE
        awards_bonus, awards_badges_str = WeightedAwardsCalculator.evaluate_awards(desc, awards_str)
        total_score = base_points + awards_bonus

        # Osobna lista premii punktowych za wiek i stację (nie są nagrodami filmowymi!)
        extra_bonuses = []

        # Wiek filmu: Nowość (2024-2026) vs Klasyk (>20 lat z wysoką notą)
        if year:
            if year >= current_year - 2:
                total_score += 4.5
                extra_bonuses.append("🆕 Nowość (+4.5 pkt)")
            elif year <= 2005 and rating > 0 and weighted_rating >= 7.2:
                total_score += 4.0
                extra_bonuses.append("💎 Klasyk (+4.0 pkt)")

        # Kanały bez reklam (komfort oglądania)
        if channel in AD_FREE_CHANNELS:
            total_score += 2.5
            extra_bonuses.append("📺 Bez reklam (+2.5 pkt)")

        final_score = round(min(100.0, max(1.0, total_score)), 1)
        if rating > 0:
            rating_fmt = f"⭐ {rating:.1f}" + (f" ({cls.format_votes(votes)})" if votes > 0 else "")
        else:
            rating_fmt = "—"
        awards_fmt = awards_badges_str if (awards_badges_str and awards_badges_str != "—") else "—"
        bonuses_fmt = " | ".join(extra_bonuses) if extra_bonuses else "—"

        return {
            "score": final_score,
            "weighted_rating": round(weighted_rating, 2),
            "base_points": round(base_points, 1),
            "awards_bonus": round(awards_bonus, 1),
            "rating": rating,
            "votes": votes,
            "rating_fmt": rating_fmt,
            "awards_fmt": awards_fmt,
            "bonuses_fmt": bonuses_fmt,
            "year": year,
        }

    def fetch_omdb_details(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        api_key = self.config.get("omdb_api_key")
        if not api_key:
            return None

        clean = re.sub(r"\s*\([^)]*\)", "", title).strip()
        params = {"t": clean, "apikey": api_key}
        if year:
            params["y"] = str(year)

        try:
            r = requests.get("http://www.omdbapi.com/", params=params, timeout=4)
            if r.status_code == 200:
                data = r.json()
                if data.get("Response") == "True":
                    imdb_rating = float(data.get("imdbRating", 0) or 0)
                    votes_str = data.get("imdbVotes", "0").replace(",", "").replace(" ", "")
                    votes = int(votes_str) if votes_str.isdigit() else 0
                    awards = data.get("Awards", "")
                    return {
                        "rating": imdb_rating,
                        "votes": votes,
                        "awards": awards,
                        "imdb_id": data.get("imdbID", ""),
                    }
        except Exception as e:
            print(f"[OMDb] Błąd zapytania dla '{title}': {e}")
        return None

    def fetch_tmdb_details(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        api_key = self.config.get("tmdb_api_key")
        if not api_key:
            return None

        clean = re.sub(r"\s*\([^)]*\)", "", title).strip()
        params = {"api_key": api_key, "query": clean, "language": "pl-PL"}
        if year:
            params["year"] = str(year)

        try:
            r = requests.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=4)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    best = results[0]
                    rating = float(best.get("vote_average", 0))
                    votes = int(best.get("vote_count", 0))
                    return {
                        "rating": rating,
                        "votes": votes,
                        "awards": "",
                        "tmdb_id": best.get("id"),
                    }
        except Exception as e:
            print(f"[TMDB] Błąd zapytania dla '{title}': {e}")
        return None

    @classmethod
    def fetch_filmweb_data(cls, title: str, year: Optional[int] = None, orig_title: Optional[str] = None) -> Optional[dict]:
        """
        Pobiera rzeczywistą ocenę, liczbę głosów oraz opis z nagrodami (synopsis)
        bezpośrednio z otwartego API Filmwebu (v1 live search + rating + description).
        """
        clean = clean_movie_title(title)
        queries = [clean]
        if ":" in clean:
            queries.append(clean.split(":")[0].strip())
        if " - " in clean:
            queries.append(clean.split(" - ")[0].strip())
        if orig_title:
            cl_orig = orig_title.strip("()")
            queries.append(cl_orig)
            if ":" in cl_orig:
                queries.append(cl_orig.split(":")[0].strip())

        for q in queries:
            try:
                r = requests.get(
                    f"https://www.filmweb.pl/api/v1/live/search?query={q}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                    timeout=3.5,
                )
                if r.status_code != 200:
                    continue
                hits = r.json().get("searchHits", [])
                for h in hits:
                    mtitle = h.get("matchedTitle")
                    fid = h.get("id")
                    if not fid or not mtitle:
                        continue
                    if not (titles_match(q, mtitle) or titles_match(clean, mtitle) or (orig_title and titles_match(orig_title.strip("()"), mtitle))):
                        continue

                    fw_year = None
                    try:
                        r_info = requests.get(
                            f"https://www.filmweb.pl/api/v1/film/{fid}/info",
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=3.0,
                        )
                        if r_info.status_code == 200:
                            fw_year = r_info.json().get("year")
                    except Exception:
                        pass

                    # Weryfikacja roku produkcji: odrzucamy remaki i inne filmy o tym samym tytule (np. Lalka 1968 vs późniejsza)
                    if year and fw_year:
                        if abs(year - fw_year) > 2:
                            continue

                    rate = None
                    votes = 0
                    try:
                        r_rate = requests.get(
                            f"https://www.filmweb.pl/api/v1/film/{fid}/rating",
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=3.0,
                        )
                        if r_rate.status_code == 200:
                            r_json = r_rate.json()
                            rate = r_json.get("rate")
                            votes = r_json.get("count", 0) or 0
                    except Exception:
                        pass

                    synopsis = ""
                    try:
                        r_desc = requests.get(
                            f"https://www.filmweb.pl/api/v1/film/{fid}/description",
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=3.0,
                        )
                        if r_desc.status_code == 200:
                            synopsis = r_desc.json().get("synopsis", "")
                    except Exception:
                        pass

                    return {
                        "filmweb_id": fid,
                        "matched_title": mtitle,
                        "rating": round(rate, 1) if rate is not None else None,
                        "votes": votes,
                        "synopsis": synopsis,
                        "year": fw_year or year,
                    }
            except Exception:
                continue
        return None

    @classmethod
    def fetch_teleman_rating(cls, link: str) -> Optional[dict]:
        """
        Pobiera rzeczywistą ocenę Filmweb, IMDb, oryginalny tytuł oraz pełny opis z podstrony filmu na teleman.pl.
        """
        if not link or "teleman.pl/tv/" not in link:
            return None
        try:
            r = requests.get(link, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=4)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            fw_el = soup.find("a", class_="filmwebRank")
            imdb_el = soup.find("a", class_="imdbRank")

            fw_val = None
            if fw_el:
                m = re.search(r"(\d+(?:[.,]\d+)?)", fw_el.get_text())
                if m:
                    fw_val = float(m.group(1).replace(",", "."))

            imdb_val = None
            imdb_id = None
            if imdb_el:
                m = re.search(r"(\d+(?:[.,]\d+)?)", imdb_el.get_text())
                if m:
                    imdb_val = float(m.group(1).replace(",", "."))
                if imdb_el.has_attr("href"):
                    m_tt = re.search(r"(tt\d+)", imdb_el["href"])
                    if m_tt:
                        imdb_id = m_tt.group(1)

            orig_title = None
            orig_el = soup.find("h2", class_="orig-title") or soup.find(class_="orig")
            if orig_el:
                orig_title = orig_el.get_text(strip=True).strip("()")

            full_desc = ""
            desc_el = soup.find("p", class_="story") or soup.find("div", class_="show-desc")
            if desc_el:
                full_desc = desc_el.get_text(strip=True)

            return {
                "filmweb_rating": fw_val,
                "imdb_rating": imdb_val,
                "imdb_id": imdb_id,
                "orig_title": orig_title,
                "full_desc": full_desc,
            }
        except Exception:
            pass
        return None

    def enrich_movie(self, program: dict) -> dict:
        title = program.get("tytul", "").strip()
        genre = program.get("gatunek", "")
        desc = program.get("opis", "")
        channel = program.get("stacja", "")
        is_film = program.get("is_film", False)

        year = self.extract_year(genre)
        norm_key = normalize_title(title)
        cache_key = f"{norm_key}_{year}" if year else norm_key

        # 1. Sprawdzenie dyskowego cache
        cached_info = self.cache.get(cache_key) or self.cache.get(norm_key)
        if cached_info:
            r = cached_info.get("rating", 0.0)
            res = self.calculate_score(
                rating=r,
                votes=cached_info.get("votes", 0),
                year=cached_info.get("year", year),
                awards_str=cached_info.get("awards", ""),
                desc=desc,
                channel=channel,
            )
            r_fmt = cached_info.get("rating_fmt") or (res["rating_fmt"] if r > 0 else "—")
            program.update({
                "ranking_pkt": res["score"],
                "ocena_glosy": r_fmt,
                "wyroznienia": res["awards_fmt"],
                "nagrody": res["awards_fmt"],
                "premie_info": res["bonuses_fmt"],
                "awards_bonus": res["awards_bonus"],
                "rok": res["year"],
            })
            return program

        # 2. Sprawdzenie wbudowanej bazy (znane klasyki kina z dokładnymi ocenami i głosami)
        builtin_info = BUILTIN_KNOWLEDGE.get(norm_key)
        if builtin_info:
            res = self.calculate_score(
                rating=builtin_info.get("rating", 7.0),
                votes=builtin_info.get("votes", 50000),
                year=builtin_info.get("year", year),
                awards_str=builtin_info.get("awards", ""),
                desc=desc,
                channel=channel,
            )
            self.cache[cache_key] = {
                "rating": builtin_info["rating"],
                "votes": builtin_info["votes"],
                "rating_fmt": res["rating_fmt"],
                "year": builtin_info["year"],
                "awards": builtin_info["awards"],
            }
            self._save_cache()
            program.update({
                "ranking_pkt": res["score"],
                "ocena_glosy": res["rating_fmt"],
                "wyroznienia": res["awards_fmt"],
                "nagrody": res["awards_fmt"],
                "premie_info": res["bonuses_fmt"],
                "awards_bonus": res["awards_bonus"],
                "rok": res["year"],
            })
            return program

        # 3. Odpytanie API (OMDb / TMDB) jeśli użytkownik podał klucze
        api_data = None
        if self.config.get("omdb_api_key"):
            api_data = self.fetch_omdb_details(title, year)
        if not api_data and self.config.get("tmdb_api_key"):
            api_data = self.fetch_tmdb_details(title, year)

        if api_data:
            rating = api_data.get("rating", 0.0)
            votes = api_data.get("votes", 0)
            awards = api_data.get("awards", "")
            res = self.calculate_score(
                rating=rating,
                votes=votes,
                year=year,
                awards_str=awards,
                desc=desc,
                channel=channel,
            )
            self.cache[cache_key] = {
                "rating": rating,
                "votes": votes,
                "rating_fmt": res["rating_fmt"],
                "year": year,
                "awards": awards,
            }
            self._save_cache()
            program.update({
                "ranking_pkt": res["score"],
                "ocena_glosy": res["rating_fmt"],
                "wyroznienia": res["awards_fmt"],
                "nagrody": res["awards_fmt"],
                "premie_info": res["bonuses_fmt"],
                "awards_bonus": res["awards_bonus"],
                "rok": res["year"],
            })
            return program

        # 4. Tryb bez ocen w bazach zewnętrznych (pozycja nieoceniona / brak danych):
        res = self.calculate_score(
            rating=0.0,
            votes=0,
            year=year,
            awards_str="",
            desc=desc,
            channel=channel,
        )

        r_fmt = "—"

        program.update({
            "ranking_pkt": res["score"],
            "ocena_glosy": r_fmt,
            "wyroznienia": res["awards_fmt"],
            "nagrody": res["awards_fmt"],
            "premie_info": res["bonuses_fmt"],
            "awards_bonus": res["awards_bonus"],
            "rok": res["year"],
        })
        return program

    def rank_all_programs(self, programs: List[dict]) -> List[dict]:
        """
        Wielowątkowe pobieranie danych ze źródeł zewnętrznych (Teleman + Filmweb Live API + IMDb),
        wyliczanie Indeksu Jakości Bayesa, ewaluacja nagród filmowych oraz sortowanie.
        """
        # 1. Zidentyfikuj pozycje filmowe wymagające pobrania ocen ze źródeł zewnętrznych
        films_to_fetch = []
        for p in programs:
            if not p.get("is_film"):
                continue
            title = p.get("tytul", "").strip()
            genre = p.get("gatunek", "")
            desc = p.get("opis", "")
            year = self.extract_year(genre)
            norm_key = normalize_title(title)
            cache_key = f"{norm_key}_{year}" if year else norm_key

            if cache_key not in self.cache and norm_key not in self.cache and norm_key not in BUILTIN_KNOWLEDGE:
                link = p.get("link", "")
                films_to_fetch.append((title, link, cache_key, norm_key, year, desc))

        # 2. Wielowątkowe pobranie danych z Telemana i API Filmweb w tle (szybkie i nieblokujące)
        if films_to_fetch:
            # Unikamy powtórzeń dla tego samego cache_key
            unique_tasks = {}
            for item in films_to_fetch:
                ckey = item[2]
                if ckey not in unique_tasks:
                    unique_tasks[ckey] = item

            def _resolve_one(item):
                title, link, cache_key, norm_key, year, desc = item
                # Źródło 1: Podstrona filmu na teleman.pl (oceny FW, IMDb, oryginalny tytuł, opis)
                teleman_res = self.fetch_teleman_rating(link) if link else {}
                if not teleman_res:
                    teleman_res = {}
                orig_title = teleman_res.get("orig_title")
                full_desc = teleman_res.get("full_desc", "")

                # Źródło 2: Otwarte API Filmwebu (wyszukiwanie po tytule polskim i oryginalnym)
                fw_data = self.fetch_filmweb_data(title, year, orig_title)

                fw_rate = fw_data.get("rating") if fw_data else teleman_res.get("filmweb_rating")
                fw_votes = fw_data.get("votes", 0) if fw_data else 0
                imdb_rate = teleman_res.get("imdb_rating")
                synopsis = fw_data.get("synopsis", "") if fw_data else ""

                # Źródło 3: API OMDb / TMDB (jeśli użytkownik podał klucze w konfiguracji)
                api_data = None
                if self.config.get("omdb_api_key"):
                    api_data = self.fetch_omdb_details(title, year)
                if not api_data and self.config.get("tmdb_api_key"):
                    api_data = self.fetch_tmdb_details(title, year)

                api_rate = api_data.get("rating", 0.0) if api_data else 0.0
                api_votes = api_data.get("votes", 0) if api_data else 0
                api_awards = api_data.get("awards", "") if api_data else ""

                # Łączymy wszystkie opisy fabuły i nagrody z API dla detektora nagród
                combined_text = f"{desc} {full_desc} {synopsis} {api_awards}".strip()
                awards_bonus, awards_badges = WeightedAwardsCalculator.evaluate_awards(combined_text, api_awards)

                # Formatowanie oceny i liczby głosów z uwzględnieniem OMDb / TMDB
                eff_imdb_rate = imdb_rate if imdb_rate is not None else (api_rate if api_rate > 0 else None)
                eff_imdb_votes = api_votes if api_votes > 0 else 0

                if fw_rate is not None and eff_imdb_rate is not None:
                    calc_r = round(fw_rate * 0.55 + eff_imdb_rate * 0.45, 1)
                    votes = max(fw_votes, eff_imdb_votes)
                    if votes > 0:
                        r_fmt = f"⭐ {calc_r:.1f} ({self.format_votes(votes)})"
                    else:
                        r_fmt = f"⭐ {calc_r:.1f} (FW {fw_rate:.1f} / IMDb {eff_imdb_rate:.1f})"
                elif fw_rate is not None:
                    calc_r = fw_rate
                    votes = fw_votes
                    if fw_votes > 0:
                        r_fmt = f"⭐ {calc_r:.1f} ({self.format_votes(fw_votes)})"
                    else:
                        r_fmt = f"⭐ {calc_r:.1f} (Filmweb)"
                elif eff_imdb_rate is not None:
                    calc_r = eff_imdb_rate
                    votes = eff_imdb_votes
                    if eff_imdb_votes > 0:
                        r_fmt = f"⭐ {calc_r:.1f} ({self.format_votes(eff_imdb_votes)})"
                    else:
                        r_fmt = f"⭐ {calc_r:.1f} (IMDb)"
                else:
                    # Rzeczywisty brak ocen w bazach - czytelna kreska '—', NIGDY sztuczne 5.5
                    calc_r = 0.0
                    votes = 0
                    r_fmt = "—"

                return {
                    "cache_key": cache_key,
                    "rating": calc_r,
                    "votes": votes,
                    "rating_fmt": r_fmt,
                    "year": (fw_data.get("year") if fw_data else year) or year,
                    "imdb_id": teleman_res.get("imdb_id") or (api_data.get("imdb_id") if api_data else None),
                    "awards": combined_text,
                    "awards_badges": awards_badges,
                    "awards_bonus": awards_bonus,
                }

            with ThreadPoolExecutor(max_workers=min(10, max(1, len(unique_tasks)))) as executor:
                for res in executor.map(_resolve_one, unique_tasks.values()):
                    if res:
                        ckey = res["cache_key"]
                        self.cache[ckey] = {
                            "rating": res["rating"],
                            "votes": res["votes"],
                            "rating_fmt": res["rating_fmt"],
                            "year": res["year"],
                            "imdb_id": res.get("imdb_id"),
                            "awards": res["awards"],
                            "awards_badges": res["awards_badges"],
                            "awards_bonus": res["awards_bonus"],
                        }
            self._save_cache()

        # 3. Wzbogać każdą pozycję i wylicz ranking
        for prog in programs:
            self.enrich_movie(prog)

        films_sorted = sorted(
            [p for p in programs if p.get("is_film")],
            key=lambda p: p.get("ranking_pkt", 0.0),
            reverse=True,
        )

        for rank_idx, f in enumerate(films_sorted):
            pkt = f.get("ranking_pkt", 0.0)
            if rank_idx == 0 and pkt >= 70:
                f["ranking_badge"] = f"🥇 {pkt:.1f} pkt"
            elif rank_idx == 1 and pkt >= 65:
                f["ranking_badge"] = f"🥈 {pkt:.1f} pkt"
            elif rank_idx == 2 and pkt >= 60:
                f["ranking_badge"] = f"🥉 {pkt:.1f} pkt"
            else:
                f["ranking_badge"] = f"{pkt:.1f} pkt"

        for p in programs:
            if not p.get("is_film"):
                pkt = p.get("ranking_pkt", 0.0)
                p["ranking_badge"] = f"{pkt:.1f} pkt"

        return programs

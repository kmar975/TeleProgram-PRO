"""
Moduł scrapingu programu telewizyjnego z serwisu teleman.pl z automatycznym
źródłem zapasowym (fallback: tv.wp.pl) w razie braku danych lub błędu.
"""

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Callable, Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from ranker import MovieRanker


# Pełna mapa stacji telewizyjnych na teleman.pl
CHANNELS_MAP: Dict[str, str] = {
    # 20 domyślnych kanałów wskazanych przez użytkownika
    "TVP Kultura": "TVP-Kultura",
    "TVP Historia": "TVP-Historia",
    "TVP Dokument": "tvp-dokument",
    "TVP Nauka": "TVP-Nauka",
    "TVP Polonia": "TVP-Polonia",
    "Nowa TV": "Nowa-TV",
    "WP": "WP",
    "TVP 1": "TVP-1",
    "TVP 2": "TVP-2",
    "Polsat": "Polsat",
    "TVN": "TVN",
    "TV4": "TV4",
    "TV Puls": "Puls",
    "TVN7": "TVN-Siedem",
    "Puls2": "Puls-2",
    "TV6": "TV6",
    "Super Polsat": "Super-Polsat",
    "Antena HD": "Antena-HD",
    "Stopklatka TV": "Stopklatka-TV",
    "Fokus TV": "Fokus-TV",

    # Dodatkowe popularne kanały (opcjonalne)
    "Polsat Film": "Polsat-Film",
    "TVN Fabuła": "TVN-Fabula",
    "TVP Seriale": "TVP-Seriale",
    "Polsat 2": "Polsat-2",
    "TVP Info": "TVP-Info",
    "TVN24": "TVN24",
    "Kino Polska": "Kino-Polska",
    "Canal+ Premium": "CanalPlus",
    "Canal+ Film": "CanalPlus-Film",
    "HBO": "HBO",
}

# 20 kanałów domyślnie zaznaczonych (zgodnie z życzeniem użytkownika)
DEFAULT_SELECTED_CHANNELS: List[str] = [
    "TVP Kultura",
    "TVP Historia",
    "TVP Dokument",
    "TVP Nauka",
    "TVP Polonia",
    "Nowa TV",
    "WP",
    "TVP 1",
    "TVP 2",
    "Polsat",
    "TVN",
    "TV4",
    "TV Puls",
    "TVN7",
    "Puls2",
    "TV6",
    "Super Polsat",
    "Antena HD",
    "Stopklatka TV",
    "Fokus TV",
]

# Mapa kanałów dla źródła zapasowego (tv.wp.pl)
WP_CHANNELS_MAP: Dict[str, str] = {
    "TVP 1": "tvp-1",
    "TVP 2": "tvp-2",
    "TVP Kultura": "tvp-kultura",
    "TVP Historia": "tvp-historia",
    "TVP Dokument": "tvp-dokument",
    "TVP Nauka": "tvp-nauka",
    "TVP Polonia": "tvp-polonia",
    "Nowa TV": "nowa-tv",
    "WP": "telewizja-wp",
    "Polsat": "polsat",
    "TVN": "tvn",
    "TV4": "tv-4",
    "TV Puls": "tv-puls",
    "TVN7": "tvn-7",
    "Puls2": "puls-2",
    "TV6": "tv-6",
    "Super Polsat": "super-polsat",
    "Antena HD": "antena-hd",
    "Stopklatka TV": "stopklatka",
    "Fokus TV": "fokus-tv",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl,en-US;q=0.9,en;q=0.8",
}


def parse_time_to_minutes(val: Optional[str]) -> Optional[int]:
    """Konwertuje ciąg 'HH:MM' lub 'HH' na liczbę minut od północy."""
    if not val or not val.strip():
        return None
    cleaned = val.strip().replace(".", ":").replace(",", ":")
    parts = cleaned.split(":")
    try:
        if len(parts) == 1:
            h = int(parts[0])
            m = 0
        elif len(parts) == 2:
            h = int(parts[0])
            m = int(parts[1])
        else:
            return None
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        return None
    return None


def is_time_in_range(show_time_str: str, start_time_str: Optional[str], end_time_str: Optional[str]) -> bool:
    """
    Sprawdza czy godzina emisji mieści się w zadanym przedziale.
    Obsługuje także przedziały nocne przechodzące przez północ (np. 22:00 – 02:00).
    """
    show_m = parse_time_to_minutes(show_time_str)
    if show_m is None:
        return True

    start_m = parse_time_to_minutes(start_time_str)
    end_m = parse_time_to_minutes(end_time_str)

    if start_m is None and end_m is None:
        return True
    if start_m is not None and end_m is None:
        return show_m >= start_m
    if start_m is None and end_m is not None:
        return show_m <= end_m

    if start_m <= end_m:
        return start_m <= show_m <= end_m
    else:
        # Zakres przez północ (np. 22:00 do 03:00)
        return show_m >= start_m or show_m <= end_m


class TelemanScraper:
    def __init__(self, timeout: int = 10):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout
        self._cache: Dict[str, List[dict]] = {}
        self.ranker = MovieRanker()

    def fetch_channel_schedule(self, channel_name: str, channel_slug: str, date_str: Optional[str] = None) -> List[dict]:
        """
        Pobiera i parsuje program dla danej stacji z teleman.pl.
        W przypadku braku danych lub błędu, automatycznie próbuje źródła zapasowego (tv.wp.pl).
        """
        cache_key = f"{channel_name}_{date_str or 'today'}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        programs = []
        try:
            programs = self._fetch_from_teleman(channel_name, channel_slug, date_str)
        except Exception as exc:
            print(f"[teleman.pl] Błąd stacji {channel_name}: {exc}")

        # Jeśli teleman nie zwrócił żadnych pozycji, użyj źródła alternatywnego
        if not programs:
            print(f"[Fallback] Próba pobrania {channel_name} ze źródła zapasowego (tv.wp.pl)...")
            try:
                programs = self._fetch_from_wp_fallback(channel_name, date_str)
            except Exception as fb_exc:
                print(f"[Fallback BŁĄD] Nie udało się pobrać {channel_name} z alternatywnego źródła: {fb_exc}")

        if programs:
            self._cache[cache_key] = programs
        return programs

    def _fetch_from_teleman(self, channel_name: str, channel_slug: str, date_str: Optional[str] = None) -> List[dict]:
        """Pobiera ramówkę bezpośrednio z serwisu teleman.pl."""
        base_url = f"https://www.teleman.pl/program-tv/stacje/{channel_slug}?hour=-1"
        if date_str:
            base_url += f"&date={date_str}"

        response = self.session.get(base_url, timeout=self.timeout)
        if response.status_code == 404:
            return []
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.find_all("li", id=lambda x: x and x.startswith("prog"))

        programs = []
        for item in items:
            em = item.find("em")
            time_str = ""
            if em:
                for child in em.contents:
                    if isinstance(child, str):
                        time_str += child
                    elif child.name != "span":
                        time_str += child.get_text()
            time_str = time_str.strip()
            if not time_str:
                continue

            parts = time_str.split(":")
            if len(parts) == 2:
                try:
                    time_str = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
                except ValueError:
                    pass

            detail = item.find("div", class_="detail")
            if not detail:
                continue

            title_a = detail.find("a")
            title = title_a.get_text(strip=True) if title_a else ""
            link = ""
            if title_a and title_a.has_attr("href"):
                link = urllib.parse.urljoin("https://www.teleman.pl", title_a["href"])

            genre_p = detail.find("p", class_="genre")
            genre = genre_p.get_text(strip=True) if genre_p else ""

            all_p = detail.find_all("p")
            desc_parts = [
                p.get_text(strip=True)
                for p in all_p
                if p != genre_p and "genre" not in p.get("class", [])
            ]
            description = " ".join(desc_parts)

            classes = item.get("class", [])
            lower_genre = genre.lower()

            is_film = (
                "cat-fil" in classes
                or ("film " in lower_genre or "film," in lower_genre or lower_genre.startswith("film"))
                or (
                    any(k in lower_genre for k in ["komedia", "dramat", "thriller", "horror", "western", "sensacyjny", "melodramat"])
                    and "serial" not in lower_genre
                    and "telenowela" not in lower_genre
                    and "magazyn" not in lower_genre
                )
            )

            category = "Inne"
            if "cat-fil" in classes or is_film:
                category = "Film"
            elif "cat-ser" in classes or "serial" in lower_genre or "telenowela" in lower_genre:
                category = "Serial"
            elif "cat-dok" in classes or "dokument" in lower_genre or "reportaż" in lower_genre:
                category = "Dokument"
            elif "cat-roz" in classes or "rozrywkowy" in lower_genre or "teleturniej" in lower_genre or "show" in lower_genre:
                category = "Rozrywka"
            elif "cat-spo" in classes or "sport" in lower_genre:
                category = "Sport"
            elif "cat-xxx" in classes:
                category = "Informacyjny / Inne"

            programs.append({
                "stacja": channel_name,
                "godzina": time_str,
                "tytul": title,
                "kategoria": category,
                "gatunek": genre,
                "opis": description,
                "link": link,
                "is_film": is_film,
                "zrodlo": "teleman.pl",
            })

        return programs

    def _fetch_from_wp_fallback(self, channel_name: str, date_str: Optional[str] = None) -> List[dict]:
        """Alternatywny parser programu z serwisu tv.wp.pl, używany w razie niedostępności kanału."""
        slug = WP_CHANNELS_MAP.get(channel_name)
        if not slug:
            clean_name = channel_name.lower().replace(" ", "-")
            slug = clean_name

        url = f"https://tv.wp.pl/kanal/{slug}"
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        programs = []

        # Wyszukaj linki z audycjami/programami
        for a in soup.find_all("a", href=lambda h: h and ("/program/" in h or "/audycja/" in h)):
            text = a.get_text(separator=" ", strip=True)
            match = re.search(r"(\d{1,2}:\d{2})", text)
            if not match:
                continue

            time_str = match.group(1)
            parts = time_str.split(":")
            if len(parts) == 2:
                time_str = f"{int(parts[0]):02d}:{int(parts[1]):02d}"

            # Tytuł po godzinie
            title_part = text.split(time_str, 1)[-1].strip()
            if not title_part or len(title_part) < 2:
                continue

            link = urllib.parse.urljoin("https://tv.wp.pl", a["href"])
            lower_title = title_part.lower()

            is_film = any(f in lower_title for f in ["film", "komedia", "dramat", "thriller", "horror"]) and "serial" not in lower_title

            programs.append({
                "stacja": channel_name,
                "godzina": time_str,
                "tytul": title_part,
                "kategoria": "Film" if is_film else "Program",
                "gatunek": "Film" if is_film else "Program telewizyjny",
                "opis": f"Pozycja programu pobrana ze źródła zapasowego (tv.wp.pl) dla stacji {channel_name}.",
                "link": link,
                "is_film": is_film,
                "zrodlo": "tv.wp.pl (źródło zapasowe)",
            })

        return programs

    def fetch_multiple_channels(
        self,
        channels: List[str],
        date_str: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[dict]:
        """
        Wielowątkowe pobieranie programu dla listy stacji.
        """
        all_programs = []
        total = len(channels)
        completed = 0

        # Zwiększamy liczbę wątków do 8, aby szybko obsłużyć 20 stacji
        with ThreadPoolExecutor(max_workers=min(8, max(1, total))) as executor:
            future_to_channel = {}
            for ch in channels:
                slug = CHANNELS_MAP.get(ch, ch.lower().replace(" ", "-"))
                future = executor.submit(self.fetch_channel_schedule, ch, slug, date_str)
                future_to_channel[future] = ch

            for future in as_completed(future_to_channel):
                ch_name = future_to_channel[future]
                completed += 1
                try:
                    progs = future.result()
                    all_programs.extend(progs)
                except Exception as exc:
                    print(f"Błąd podczas pobierania {ch_name}: {exc}")
                if progress_callback:
                    progress_callback(completed, total, ch_name)

        # Wyliczanie rankingu, ocen i nagród dla pobranych pozycji
        self.ranker.rank_all_programs(all_programs)
        return all_programs

    def clear_cache(self):
        """Czyści pamięć podręczną pobranych stron."""
        self._cache.clear()

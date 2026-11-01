"""
Nowoczesny interfejs graficzny GUI (v3.0) dla aplikacji Program TV.
Zbudowany w oparciu o CustomTkinter z algorytmem rankingowym (Indeks Jakości 0-100 pkt),
podwójnym widokiem (Tabela PRO / Karty filmowe) oraz trwałym cache (movies_cache.json).
"""

import csv
import io
import os
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

# Ciche zaimportowanie CustomTkinter z wyciszeniem ostrzeżeń czcionki
_old_stderr = sys.stderr
sys.stderr = io.StringIO()
try:
    import customtkinter as ctk
finally:
    sys.stderr = _old_stderr

from scraper import (
    CHANNELS_MAP,
    DEFAULT_SELECTED_CHANNELS,
    TelemanScraper,
    is_time_in_range,
    parse_time_to_minutes,
)
from ranker import MovieRanker

# Paleta kolorów UI (Dark Obsidian / Apple Light)
THEMES = {
    "dark": {
        "bg": "#0d1017",
        "surface": "#161b26",
        "surface_elevated": "#1f2637",
        "surface_card": "#181d2a",
        "border": "#283144",
        "accent": "#4f46e5",
        "accent_hover": "#4338ca",
        "gold": "#f59e0b",
        "gold_bg": "#2e230f",
        "cyan": "#06b6d4",
        "silver": "#94a3b8",
        "text_primary": "#f8fafc",
        "text_secondary": "#94a3b8",
        "text_muted": "#64748b",
        "tree_bg": "#141824",
        "tree_alt": "#181d2a",
        "tree_selected": "#312e81",
        "heading_bg": "#1e2436",
    },
    "light": {
        "bg": "#f1f5f9",
        "surface": "#ffffff",
        "surface_elevated": "#f8fafc",
        "surface_card": "#ffffff",
        "border": "#cbd5e1",
        "accent": "#4f46e5",
        "accent_hover": "#4338ca",
        "gold": "#b45309",
        "gold_bg": "#fef3c7",
        "cyan": "#0891b2",
        "silver": "#64748b",
        "text_primary": "#0f172a",
        "text_secondary": "#475569",
        "text_muted": "#64748b",
        "tree_bg": "#ffffff",
        "tree_alt": "#f8fafc",
        "tree_selected": "#e0e7ff",
        "heading_bg": "#e2e8f0",
    },
}


class TVProgramApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("TeleProgram PRO - Ranking TV z teleman.pl")

        # Obliczenie proporcji dopasowanych do monitora (zbalansowana wysokość - dłuższa niż v1, krótsza niż v2)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        init_w = min(1800, max(1460, int(screen_w * 0.93)))
        init_h = max(880, min(screen_h - 85, int(screen_h * 0.92)))
        pos_x = max(0, (screen_w - init_w) // 2)
        pos_y = max(12, (screen_h - init_h) // 2 - 15)
        self.geometry(f"{init_w}x{init_h}+{pos_x}+{pos_y}")
        self.minsize(1200, 750)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Rozmiary czcionki w tabeli (duże, czytelne domyślnie)
        self.current_font_size = 13
        self.current_row_height = 38

        # Inicjalizacja scrapera i stanu
        self.scraper = TelemanScraper()
        self.ranker = self.scraper.ranker
        self.all_programs: List[dict] = []
        self.filtered_programs: List[dict] = []
        self.is_fetching = False
        self.current_theme = "dark"
        self.active_view = "tabela"  # "tabela" lub "karty"

        # Stan sortowania - domyślnie po rankingu (najlepsze najpierw)
        self.sort_column = "ranking_pkt"
        self.sort_reverse = True

        # Zmienne kontrolne
        self.channel_vars = {}
        self.channel_checkboxes = {}
        self.only_movies_var = ctk.BooleanVar(value=True)  # Kompatybilność wsteczna
        self.category_filter_var = ctk.StringVar(value="filmy")
        self.search_query_var = ctk.StringVar(value="")
        self.channel_search_var = ctk.StringVar(value="")
        self.status_var = ctk.StringVar(value="Gotowy do pobrania programu telewizyjnego.")

        # Wskaźniki KPI
        self.stat_movies_var = ctk.StringVar(value="🎬 Filmy: 0")
        self.stat_stations_var = ctk.StringVar(value=f"📡 Stacje: {len(DEFAULT_SELECTED_CHANNELS)}")
        self.stat_time_var = ctk.StringVar(value="⏰ 20:00 – 23:30")
        self.stat_top_var = ctk.StringVar(value="🏆 Top film: —")

        # Opcje daty
        self.date_options = self._generate_date_options()
        self.selected_date_label = ctk.StringVar(value=self.date_options[0][0])

        # Styl tabeli ttk
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Konstrukcja UI
        self._create_modern_layout()
        self._apply_treeview_styling("dark")
        self._set_default_channels()

        # Automatyczny start pobierania w tle po 350 ms
        self.after(350, self.start_fetching_thread)

    def _generate_date_options(self):
        days_names = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]
        options = []
        now = datetime.now()
        for i in range(7):
            d = now + timedelta(days=i)
            day_name = days_names[d.weekday()]
            date_str = d.strftime("%Y-%m-%d")
            if i == 0:
                label = f"Dziś ({day_name}, {d.strftime('%d.%m')})"
            elif i == 1:
                label = f"Jutro ({day_name}, {d.strftime('%d.%m')})"
            else:
                label = f"{day_name}, {d.strftime('%d.%m.%Y')}"
            options.append((label, date_str))
        return options

    def _get_current_selected_date_slug(self) -> Optional[str]:
        cur_label = self.selected_date_label.get()
        for label, date_slug in self.date_options:
            if label == cur_label:
                return date_slug
        return None

    # --- Architektura układu graficznego ---

    def _create_modern_layout(self):
        self.grid_columnconfigure(0, weight=0, minsize=340)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=1)  # Main area
        self.grid_rowconfigure(2, weight=0)  # Status bar

        self._build_top_header()
        self._build_sidebar()
        self._build_main_workspace()
        self._build_status_bar()

    def _build_top_header(self):
        pal = THEMES[self.current_theme]
        self.header_frame = ctk.CTkFrame(
            self,
            corner_radius=0,
            height=64,
            fg_color=pal["surface"],
            border_width=1,
            border_color=pal["border"],
        )
        self.header_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.header_frame.grid_columnconfigure(1, weight=1)

        # Lewa strona: Nowoczesne Logo
        logo_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        logo_box.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        icon_badge = ctk.CTkLabel(
            logo_box,
            text="🏆",
            font=ctk.CTkFont(size=24),
            width=36,
            height=36,
            fg_color=pal["accent"],
            corner_radius=8,
        )
        icon_badge.pack(side="left", padx=(0, 10))

        title_box = ctk.CTkFrame(logo_box, fg_color="transparent")
        title_box.pack(side="left")

        app_title = ctk.CTkLabel(
            title_box,
            text="TeleProgram PRO  •  Ranking Filmowy",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=pal["text_primary"],
        )
        app_title.pack(anchor="w")

        app_subtitle = ctk.CTkLabel(
            title_box,
            text="Indeks Jakości (0-100 pkt) • Wzór Bayesa • Nagrody • OMDb / TMDB",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=pal["text_secondary"],
        )
        app_subtitle.pack(anchor="w")

        # Środek: Wizualne pigułki wskaźników (KPI Badges)
        metrics_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        metrics_box.grid(row=0, column=1, padx=10, pady=10)

        self.badge_movies = ctk.CTkLabel(
            metrics_box,
            textvariable=self.stat_movies_var,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            text_color=pal["gold"],
            corner_radius=20,
            padx=14,
            pady=6,
        )
        self.badge_movies.pack(side="left", padx=4)

        self.badge_top = ctk.CTkLabel(
            metrics_box,
            textvariable=self.stat_top_var,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            text_color=pal["cyan"],
            corner_radius=20,
            padx=14,
            pady=6,
        )
        self.badge_top.pack(side="left", padx=4)

        self.badge_time = ctk.CTkLabel(
            metrics_box,
            textvariable=self.stat_time_var,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            text_color=pal["text_primary"],
            corner_radius=20,
            padx=14,
            pady=6,
        )
        self.badge_time.pack(side="left", padx=4)

        # Prawa strona: Przełącznik widoku, Dzień, Rozmiar czcionki, Motyw
        controls_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        controls_box.grid(row=0, column=2, padx=20, pady=10, sticky="e")

        # Przełącznik: Tabela PRO / Karty
        self.view_switcher = ctk.CTkSegmentedButton(
            controls_box,
            values=["📋 Tabela PRO", "🎴 Karty filmowe"],
            command=self._on_view_changed,
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color=pal["accent"],
            selected_hover_color=pal["accent_hover"],
            height=32,
        )
        self.view_switcher.set("📋 Tabela PRO")
        self.view_switcher.pack(side="left", padx=(0, 12))

        # Menu wyboru dnia
        date_labels = [opt[0] for opt in self.date_options]
        self.date_menu = ctk.CTkOptionMenu(
            controls_box,
            values=date_labels,
            variable=self.selected_date_label,
            command=self._on_date_changed,
            width=165,
            height=32,
            font=ctk.CTkFont(size=12),
            fg_color=pal["surface_elevated"],
            button_color=pal["accent"],
        )
        self.date_menu.pack(side="left", padx=(0, 8))

        # Wybór rozmiaru czcionki tabeli
        self.font_size_menu = ctk.CTkOptionMenu(
            controls_box,
            values=["Czcionka: Duża (13pt)", "Czcionka: Bardzo duża (15pt)", "Czcionka: Średnia (11pt)"],
            command=self._on_font_size_changed,
            width=175,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["surface_elevated"],
            button_color=pal["accent"],
        )
        self.font_size_menu.pack(side="left", padx=(0, 8))

        # Przełącznik motywu
        self.theme_btn = ctk.CTkButton(
            controls_box,
            text="🌙 Ciemny",
            width=85,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._toggle_theme,
        )
        self.theme_btn.pack(side="left")

    def _build_sidebar(self):
        pal = THEMES[self.current_theme]
        self.sidebar = ctk.CTkScrollableFrame(
            self,
            width=340,
            corner_radius=0,
            fg_color=pal["surface"],
            border_width=1,
            border_color=pal["border"],
        )
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # SEKCJA 1: Wybór kanałów
        ch_title_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        ch_title_box.pack(fill="x", padx=15, pady=(15, 6))

        ch_header = ctk.CTkLabel(
            ch_title_box,
            text="Stacje telewizyjne",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=pal["text_primary"],
        )
        ch_header.pack(side="left")

        self.ch_count_lbl = ctk.CTkLabel(
            ch_title_box,
            text=f"{len(DEFAULT_SELECTED_CHANNELS)} zazn.",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=pal["cyan"],
        )
        self.ch_count_lbl.pack(side="right")

        self.ch_search_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="🔍 Filtruj stacje na liście...",
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=pal["surface_elevated"],
            border_color=pal["border"],
            textvariable=self.channel_search_var,
        )
        self.ch_search_entry.pack(fill="x", padx=15, pady=(0, 6))
        self.ch_search_entry.bind("<KeyRelease>", lambda e: self._filter_channel_checkboxes())

        chip_bar1 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        chip_bar1.pack(fill="x", padx=15, pady=(0, 4))

        btn_def20 = ctk.CTkButton(
            chip_bar1,
            text="⭐ Domyślne 20",
            width=100,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["accent"],
            hover_color=pal["accent_hover"],
            command=self._set_default_channels,
        )
        btn_def20.pack(side="left", padx=(0, 4))

        btn_tvp = ctk.CTkButton(
            chip_bar1,
            text="Tylko TVP",
            width=75,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._select_tvp_only,
        )
        btn_tvp.pack(side="left", padx=(0, 4))

        btn_comm = ctk.CTkButton(
            chip_bar1,
            text="Komercyjne",
            width=85,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._select_commercial_only,
        )
        btn_comm.pack(side="left")

        chip_bar2 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        chip_bar2.pack(fill="x", padx=15, pady=(0, 8))

        btn_all = ctk.CTkButton(
            chip_bar2,
            text="Zaznacz wszystkie",
            width=135,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._select_all_channels,
        )
        btn_all.pack(side="left", padx=(0, 4))

        btn_none = ctk.CTkButton(
            chip_bar2,
            text="Odznacz",
            width=70,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._deselect_all_channels,
        )
        btn_none.pack(side="left")

        # Kontener checkboxów stacji
        self.channels_container = ctk.CTkFrame(
            self.sidebar,
            fg_color=pal["surface_card"],
            corner_radius=10,
            border_width=1,
            border_color=pal["border"],
        )
        self.channels_container.pack(fill="x", padx=15, pady=(0, 15))
        self.channels_container.grid_columnconfigure(0, weight=1)
        self.channels_container.grid_columnconfigure(1, weight=1)

        channels_list = list(CHANNELS_MAP.keys())
        for idx, ch_name in enumerate(channels_list):
            var = ctk.BooleanVar(value=ch_name in DEFAULT_SELECTED_CHANNELS)
            self.channel_vars[ch_name] = var
            cb = ctk.CTkCheckBox(
                self.channels_container,
                text=ch_name,
                variable=var,
                font=ctk.CTkFont(size=11),
                checkbox_width=16,
                checkbox_height=16,
                fg_color=pal["accent"],
                command=self._on_channel_checkbox_toggled,
            )
            r = idx // 2
            c = idx % 2
            cb.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            self.channel_checkboxes[ch_name] = (cb, r, c)

        # SEKCJA 2: Przedział godzinowy
        time_header = ctk.CTkLabel(
            self.sidebar,
            text="Przedział godzinowy",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=pal["text_primary"],
            anchor="w",
        )
        time_header.pack(fill="x", padx=15, pady=(0, 6))

        time_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=pal["surface_card"],
            corner_radius=10,
            border_width=1,
            border_color=pal["border"],
        )
        time_card.pack(fill="x", padx=15, pady=(0, 8))
        time_card.grid_columnconfigure((1, 3), weight=1)

        lbl_od = ctk.CTkLabel(time_card, text="Od:", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_od.grid(row=0, column=0, padx=(10, 4), pady=8, sticky="w")

        self.entry_from = ctk.CTkEntry(
            time_card,
            width=65,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            border_color=pal["border"],
        )
        self.entry_from.insert(0, "20:00")
        self.entry_from.grid(row=0, column=1, padx=(0, 6), pady=8, sticky="ew")
        self.entry_from.bind("<KeyRelease>", lambda e: self._on_time_input_change())

        lbl_do = ctk.CTkLabel(time_card, text="Do:", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_do.grid(row=0, column=2, padx=(4, 4), pady=8, sticky="w")

        self.entry_to = ctk.CTkEntry(
            time_card,
            width=65,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            border_color=pal["border"],
        )
        self.entry_to.insert(0, "23:30")
        self.entry_to.grid(row=0, column=3, padx=(0, 10), pady=8, sticky="ew")
        self.entry_to.bind("<KeyRelease>", lambda e: self._on_time_input_change())

        preset_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        preset_box.pack(fill="x", padx=15, pady=(0, 15))
        preset_box.grid_columnconfigure((0, 1), weight=1)

        p_prime = ctk.CTkButton(
            preset_box,
            text="🌙 Prime Time (20:00 - 23:30)",
            height=26,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=lambda: self._set_time_preset("20:00", "23:30"),
        )
        p_prime.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        p_all = ctk.CTkButton(
            preset_box,
            text="☀️ Cały dzień",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=lambda: self._set_time_preset("00:00", "23:59"),
        )
        p_all.grid(row=1, column=0, sticky="ew", padx=(0, 2))

        p_afternoon = ctk.CTkButton(
            preset_box,
            text="🌆 Popołudnie (15-20)",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=lambda: self._set_time_preset("15:00", "20:00"),
        )
        p_afternoon.grid(row=1, column=1, sticky="ew", padx=(2, 0))

        p_now = ctk.CTkButton(
            preset_box,
            text="⏰ Od teraz (+3h)",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._set_time_now_plus_3,
        )
        p_now.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # SEKCJA 3: Filtr repertuaru i wyszukiwarka
        filter_header = ctk.CTkLabel(
            self.sidebar,
            text="Filtr repertuaru",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=pal["text_primary"],
            anchor="w",
        )
        filter_header.pack(fill="x", padx=15, pady=(0, 6))

        self.category_segmented = ctk.CTkSegmentedButton(
            self.sidebar,
            values=["🎬 Tylko filmy", "📺 Wszystkie pozycje"],
            command=self._on_category_segment_changed,
            font=ctk.CTkFont(size=11, weight="bold"),
            selected_color=pal["gold"],
            selected_hover_color=pal["gold"],
            height=30,
        )
        self.category_segmented.set("🎬 Tylko filmy")
        self.category_segmented.pack(fill="x", padx=15, pady=(0, 8))

        self.search_entry = ctk.CTkEntry(
            self.sidebar,
            placeholder_text="🔍 Szukaj w tytule, gatunku, opisie...",
            textvariable=self.search_query_var,
            font=ctk.CTkFont(size=11),
            fg_color=pal["surface_card"],
            border_color=pal["border"],
            height=30,
        )
        self.search_entry.pack(fill="x", padx=15, pady=(0, 18))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filters())

        # SEKCJA 4: Akcje
        self.btn_fetch = ctk.CTkButton(
            self.sidebar,
            text="⚡ Pobierz / Odśwież program",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=42,
            fg_color=pal["accent"],
            hover_color=pal["accent_hover"],
            corner_radius=8,
            command=self.start_fetching_thread,
        )
        self.btn_fetch.pack(fill="x", padx=15, pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(
            self.sidebar,
            orientation="horizontal",
            height=6,
            progress_color=pal["accent"],
            fg_color=pal["surface_elevated"],
        )
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 8))
        self.progress_bar.set(0)

        self.btn_export = ctk.CTkButton(
            self.sidebar,
            text="📊 Eksportuj ranking do CSV",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=38,
            fg_color="#064e3b" if self.current_theme == "dark" else "#d1fae5",
            hover_color="#047857" if self.current_theme == "dark" else "#a7f3d0",
            text_color="#34d399" if self.current_theme == "dark" else "#065f46",
            border_width=1,
            border_color="#059669" if self.current_theme == "dark" else "#10b981",
            corner_radius=8,
            command=self.export_to_csv,
        )
        self.btn_export.pack(fill="x", padx=15, pady=(0, 15))

    def _build_main_workspace(self):
        pal = THEMES[self.current_theme]
        self.workspace = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.workspace.grid(row=1, column=1, sticky="nsew", padx=15, pady=(10, 10))
        self.workspace.grid_columnconfigure(0, weight=1)
        self.workspace.grid_rowconfigure(0, weight=1)  # Table or Cards
        self.workspace.grid_rowconfigure(1, weight=0)  # Preview Sheet

        # 1. Kontener widoku Tabeli PRO
        self.table_container = ctk.CTkFrame(
            self.workspace,
            corner_radius=10,
            fg_color=pal["surface_card"],
            border_width=1,
            border_color=pal["border"],
        )
        self.table_container.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.table_container.grid_columnconfigure(0, weight=1)
        self.table_container.grid_rowconfigure(1, weight=1)

        # Belka szybkiego sortowania i ustawień nad tabelą
        sort_bar = ctk.CTkFrame(self.table_container, fg_color="transparent")
        sort_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 8))

        lbl_sort = ctk.CTkLabel(sort_bar, text="Sortowanie:", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_sort.pack(side="left", padx=(4, 8))

        self.btn_sort_rank = ctk.CTkButton(
            sort_bar,
            text="🏆 Sortuj wg Rankingu (najlepsze)",
            width=190,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["gold_bg"],
            text_color=pal["gold"],
            hover_color=pal["surface_elevated"],
            command=self._sort_by_ranking,
        )
        self.btn_sort_rank.pack(side="left", padx=(0, 6))

        self.btn_sort_time = ctk.CTkButton(
            sort_bar,
            text="⏰ Sortuj wg Godziny",
            width=160,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._sort_by_time,
        )
        self.btn_sort_time.pack(side="left", padx=(0, 15))

        btn_api_settings = ctk.CTkButton(
            sort_bar,
            text="⚙️ Klucze API (OMDb / TMDB)",
            width=180,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=self._open_api_settings_dialog,
        )
        btn_api_settings.pack(side="right", padx=(0, 4))

        self.btn_export_toolbar = ctk.CTkButton(
            sort_bar,
            text="📥 Eksport CSV",
            width=120,
            height=28,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            text_color=pal["text_primary"],
            command=self.export_to_csv,
        )
        self.btn_export_toolbar.pack(side="right", padx=(0, 8))

        # Tabela Treeview
        columns = ("ranking_badge", "godzina", "stacja", "tytul", "ocena_glosy", "wyroznienia", "gatunek", "opis", "zrodlo")
        self.tree = ttk.Treeview(
            self.table_container,
            columns=columns,
            show="headings",
            style="Custom.Treeview",
            selectmode="browse",
        )

        self.col_headings = {
            "ranking_badge": "Ranking (pkt)",
            "godzina": "Godz.",
            "stacja": "Kanał",
            "tytul": "Tytuł pozycji",
            "ocena_glosy": "Ocena (Głosy)",
            "wyroznienia": "Nagrody filmowe",
            "gatunek": "Gatunek",
            "opis": "Opis fabuły",
            "zrodlo": "Źródło",
        }

        col_widths = {
            "ranking_badge": 125,
            "godzina": 80,
            "stacja": 125,
            "tytul": 290,
            "ocena_glosy": 135,
            "wyroznienia": 240,
            "gatunek": 210,
            "opis": 430,
            "zrodlo": 100,
        }

        for col in columns:
            self.tree.heading(col, text=self.col_headings[col], command=lambda c=col: self._sort_by_column(c))
            anchor = "center" if col in ("ranking_badge", "godzina", "stacja", "ocena_glosy", "zrodlo") else "w"
            self.tree.column(col, width=col_widths[col], minwidth=60, anchor=anchor)

        v_scroll = ttk.Scrollbar(self.table_container, orient="vertical", command=self.tree.yview)
        h_scroll = ttk.Scrollbar(self.table_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        self.tree.grid(row=1, column=0, sticky="nsew")
        v_scroll.grid(row=1, column=1, sticky="ns")
        h_scroll.grid(row=2, column=0, sticky="ew")

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._show_context_menu)

        # 2. Kontener widoku Kart Filmowych
        self.cards_scroll = ctk.CTkScrollableFrame(
            self.workspace,
            corner_radius=10,
            fg_color=pal["surface_card"],
            border_width=1,
            border_color=pal["border"],
        )

        # 3. Karta Podglądu Szczegółów (Hero Preview Sheet)
        self._build_preview_drawer(self.workspace)
        self._build_context_menu()

    def _build_preview_drawer(self, parent):
        pal = THEMES[self.current_theme]
        self.preview_card = ctk.CTkFrame(
            parent,
            corner_radius=10,
            fg_color=pal["surface"],
            border_width=1,
            border_color=pal["border"],
            height=215,
        )
        self.preview_card.grid(row=1, column=0, sticky="ew")
        self.preview_card.grid_columnconfigure(0, weight=1)
        self.preview_card.grid_propagate(False)

        top_bar = ctk.CTkFrame(self.preview_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=16, pady=(10, 4))

        self.detail_title_lbl = ctk.CTkLabel(
            top_bar,
            text="Wybierz pozycję z tabeli lub kart, aby zobaczyć ocenę, nagrody i opis",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=pal["text_primary"],
            anchor="w",
        )
        self.detail_title_lbl.pack(side="left", fill="x", expand=True)

        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right")

        self.btn_trailer = ctk.CTkButton(
            btn_box,
            text="🎬 Szukaj zwiastuna",
            width=140,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            state="disabled",
            command=self._search_trailer,
        )
        self.btn_trailer.pack(side="left", padx=(0, 6))

        self.btn_open_web = ctk.CTkButton(
            btn_box,
            text="🌐 Otwórz w teleman.pl",
            width=155,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=pal["accent"],
            hover_color=pal["accent_hover"],
            state="disabled",
            command=self._open_in_browser,
        )
        self.btn_open_web.pack(side="left", padx=(0, 6))

        self.btn_copy_info = ctk.CTkButton(
            btn_box,
            text="📋 Kopiuj",
            width=85,
            height=32,
            font=ctk.CTkFont(size=12),
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            state="disabled",
            command=self._copy_selected_info,
        )
        self.btn_copy_info.pack(side="left")

        # Pasek metadanych (Ranking, Ocena, Nagrody)
        self.detail_rank_lbl = ctk.CTkLabel(
            self.preview_card,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=pal["gold"],
            anchor="w",
        )
        self.detail_rank_lbl.pack(fill="x", padx=16, pady=(0, 2))

        self.detail_meta_lbl = ctk.CTkLabel(
            self.preview_card,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=pal["text_secondary"],
            anchor="w",
        )
        self.detail_meta_lbl.pack(fill="x", padx=16, pady=(0, 6))

        self.detail_desc_box = ctk.CTkTextbox(
            self.preview_card,
            height=100,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
            fg_color=pal["surface_elevated"],
            border_width=0,
            activate_scrollbars=True,
        )
        self.detail_desc_box.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.detail_desc_box.insert("1.0", "Brak wybranej pozycji.")
        self.detail_desc_box.configure(state="disabled")

        self.current_selected_link = ""
        self.current_selected_prog = None

    def _build_context_menu(self):
        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="🌐 Otwórz w przeglądarce", command=self._open_in_browser)
        self.context_menu.add_command(label="🎬 Szukaj zwiastuna na YouTube", command=self._search_trailer)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋 Kopiuj tytuł", command=self._copy_title)
        self.context_menu.add_command(label="📋 Kopiuj pełne informacje z rankingiem", command=self._copy_selected_info)

    def _show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self._on_tree_select(None)
            self.context_menu.post(event.x_root, event.y_root)

    def _build_status_bar(self):
        pal = THEMES[self.current_theme]
        self.status_frame = ctk.CTkFrame(
            self,
            height=30,
            corner_radius=0,
            fg_color=pal["surface"],
            border_width=1,
            border_color=pal["border"],
        )
        self.status_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            self.status_frame,
            textvariable=self.status_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=pal["text_secondary"],
            anchor="w",
        )
        self.lbl_status.grid(row=0, column=0, padx=16, pady=4, sticky="w")

        lbl_author = ctk.CTkLabel(
            self.status_frame,
            text="TeleProgram PRO • Indeks Bayesa • OMDb / TMDB • teleman.pl",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=pal["text_muted"],
            anchor="e",
        )
        lbl_author.grid(row=0, column=1, padx=16, pady=4, sticky="e")

    # --- Stylowanie i Przełączanie Motywu ---

    def _apply_treeview_styling(self, mode: str):
        pal = THEMES[mode]

        self.style.configure(
            "Custom.Treeview",
            background=pal["tree_bg"],
            foreground=pal["text_primary"],
            fieldbackground=pal["tree_bg"],
            rowheight=self.current_row_height,
            font=("Segoe UI", self.current_font_size),
            borderwidth=0,
        )
        self.style.configure(
            "Custom.Treeview.Heading",
            background=pal["heading_bg"],
            foreground=pal["text_primary"],
            font=("Segoe UI", self.current_font_size, "bold"),
            relief="flat",
            padding=(8, 10),
        )
        self.style.map("Custom.Treeview.Heading", background=[("active", pal["accent"])], foreground=[("active", "#ffffff")])
        self.style.map("Custom.Treeview", background=[("selected", pal["tree_selected"])], foreground=[("selected", "#ffffff")])

        # Wyróżnienia wierszy
        self.tree.tag_configure("top_gold", background="#382d11" if mode == "dark" else "#fef3c7")
        self.tree.tag_configure("top_silver", background="#2a2f3d" if mode == "dark" else "#f1f5f9")
        self.tree.tag_configure("razzie_row", background="#38191d" if mode == "dark" else "#fee2e2", foreground="#f87171" if mode == "dark" else "#b91c1c")
        self.tree.tag_configure("film_row", background=pal["gold_bg"])
        self.tree.tag_configure("alt_row", background=pal["tree_alt"])
        self.tree.tag_configure("normal_row", background=pal["tree_bg"])

    def _on_font_size_changed(self, choice: str):
        if "Bardzo duża" in choice:
            self.current_font_size = 15
            self.current_row_height = 44
        elif "Średnia" in choice:
            self.current_font_size = 11
            self.current_row_height = 32
        else:
            self.current_font_size = 13
            self.current_row_height = 38
        self._apply_treeview_styling(self.current_theme)
        self._refresh_treeview()

    def _toggle_theme(self):
        new_mode = "light" if self.current_theme == "dark" else "dark"
        self.current_theme = new_mode
        ctk.set_appearance_mode("Light" if new_mode == "light" else "Dark")
        self.theme_btn.configure(text="🌙 Ciemny" if new_mode == "light" else "☀️ Jasny")
        is_dark = new_mode == "dark"
        self.btn_export.configure(
            fg_color="#064e3b" if is_dark else "#d1fae5",
            hover_color="#047857" if is_dark else "#a7f3d0",
            text_color="#34d399" if is_dark else "#065f46",
            border_color="#059669" if is_dark else "#10b981",
        )
        self._apply_treeview_styling(new_mode)
        self._refresh_treeview()

    # --- Przełączanie Widoków (Tabela vs Karty) ---

    def _on_view_changed(self, view_choice: str):
        if "Karty" in view_choice:
            self.active_view = "karty"
            self.table_container.grid_forget()
            self.cards_scroll.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
            self._render_cards_view()
        else:
            self.active_view = "tabela"
            self.cards_scroll.grid_forget()
            self.table_container.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
            self._refresh_treeview()

    def _render_cards_view(self):
        pal = THEMES[self.current_theme]

        for child in self.cards_scroll.winfo_children():
            child.destroy()

        if not self.filtered_programs:
            empty_box = ctk.CTkFrame(self.cards_scroll, fg_color="transparent")
            empty_box.pack(fill="both", expand=True, pady=60)
            lbl = ctk.CTkLabel(
                empty_box,
                text="Brak pozycji spełniających wybrane kryteria.",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=pal["text_secondary"],
            )
            lbl.pack()
            return

        for prog in self.filtered_programs:
            is_razzie = "🍓" in prog.get("wyroznienia", "")
            card_border = (
                ("#7f1d1d" if self.current_theme == "dark" else "#fca5a5")
                if is_razzie
                else pal["border"]
            )
            card = ctk.CTkFrame(
                self.cards_scroll,
                corner_radius=12,
                fg_color=pal["surface"],
                border_width=1,
                border_color=card_border,
            )
            card.pack(fill="x", padx=10, pady=5)

            # Belka górna karty: Ranking, Ocena, Godzina, Stacja
            top_bar = ctk.CTkFrame(card, fg_color="transparent")
            top_bar.pack(fill="x", padx=14, pady=(10, 4))

            # Ranking pkt badge
            rank_text = prog.get("ranking_badge", f"{prog.get('ranking_pkt', 0):.1f} pkt")
            is_top = "🥇" in rank_text or "🥈" in rank_text or "🥉" in rank_text
            rank_badge = ctk.CTkLabel(
                top_bar,
                text=rank_text,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color=pal["gold"] if is_top else pal["surface_elevated"],
                text_color="#000000" if is_top else pal["gold"],
                corner_radius=6,
                padx=10,
                pady=3,
            )
            rank_badge.pack(side="left", padx=(0, 8))

            if prog.get("ocena_glosy"):
                rating_badge = ctk.CTkLabel(
                    top_bar,
                    text=prog["ocena_glosy"],
                    font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                    fg_color=pal["surface_elevated"],
                    text_color=pal["text_primary"],
                    corner_radius=6,
                    padx=10,
                    pady=3,
                )
                rating_badge.pack(side="left", padx=(0, 8))

            time_badge = ctk.CTkLabel(
                top_bar,
                text=prog["godzina"],
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color=pal["accent"],
                text_color="#ffffff",
                corner_radius=6,
                padx=10,
                pady=3,
            )
            time_badge.pack(side="left", padx=(0, 8))

            stacja_badge = ctk.CTkLabel(
                top_bar,
                text=prog["stacja"],
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                fg_color=pal["surface_elevated"],
                text_color=pal["cyan"],
                corner_radius=6,
                padx=10,
                pady=3,
            )
            stacja_badge.pack(side="left", padx=(0, 8))

            zrodlo_lbl = ctk.CTkLabel(
                top_bar,
                text=prog.get("zrodlo", "teleman.pl"),
                font=ctk.CTkFont(size=11),
                text_color=pal["text_muted"],
            )
            zrodlo_lbl.pack(side="right")

            # Tytuł
            title_lbl = ctk.CTkLabel(
                card,
                text=prog["tytul"],
                font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
                text_color=pal["text_primary"],
                anchor="w",
            )
            title_lbl.pack(fill="x", padx=14, pady=(4, 2))

            # Nagrody filmowe (jeśli są)
            awards = prog.get("nagrody") or prog.get("wyroznienia")
            if awards and awards != "—":
                awards_bonus = prog.get("awards_bonus")
                bonus_str = f" ({awards_bonus:+0.1f} pkt)" if awards_bonus is not None else ""
                awards_lbl = ctk.CTkLabel(
                    card,
                    text=f"Nagrody: {awards}{bonus_str}",
                    font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                    text_color="#ef4444" if is_razzie else pal["gold"],
                    anchor="w",
                )
                awards_lbl.pack(fill="x", padx=14, pady=(0, 2))

            # Dodatkowe premie rankingowe (wiek / stacja)
            premie = prog.get("premie_info")
            if premie and premie != "—":
                premie_lbl = ctk.CTkLabel(
                    card,
                    text=f"Premie: {premie}",
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=pal["cyan"],
                    anchor="w",
                )
                premie_lbl.pack(fill="x", padx=14, pady=(0, 2))

            # Gatunek / metadane
            if prog.get("gatunek"):
                genre_lbl = ctk.CTkLabel(
                    card,
                    text=prog["gatunek"],
                    font=ctk.CTkFont(family="Segoe UI", size=13),
                    text_color=pal["text_secondary"],
                    anchor="w",
                )
                genre_lbl.pack(fill="x", padx=14, pady=(0, 4))

            # Krótki opis
            if prog.get("opis"):
                desc_lbl = ctk.CTkLabel(
                    card,
                    text=prog["opis"][:240] + ("..." if len(prog["opis"]) > 240 else ""),
                    font=ctk.CTkFont(family="Segoe UI", size=12),
                    text_color=pal["text_muted"],
                    anchor="w",
                    justify="left",
                    wraplength=1050,
                )
                desc_lbl.pack(fill="x", padx=14, pady=(0, 8))

            # Pasek akcji karty
            act_bar = ctk.CTkFrame(card, fg_color="transparent")
            act_bar.pack(fill="x", padx=14, pady=(0, 10))

            btn_sel = ctk.CTkButton(
                act_bar,
                text="Szczegóły ↗",
                width=100,
                height=28,
                font=ctk.CTkFont(size=12),
                fg_color=pal["surface_elevated"],
                hover_color=pal["border"],
                command=lambda p=prog: self._select_program_card(p),
            )
            btn_sel.pack(side="left", padx=(0, 6))

            btn_yt = ctk.CTkButton(
                act_bar,
                text="🎬 Zwiastun",
                width=95,
                height=28,
                font=ctk.CTkFont(size=12),
                fg_color=pal["surface_elevated"],
                hover_color=pal["border"],
                command=lambda t=prog["tytul"]: webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote(t + ' zwiastun trailer')}"),
            )
            btn_yt.pack(side="left", padx=(0, 6))

            if prog.get("link"):
                btn_link = ctk.CTkButton(
                    act_bar,
                    text="🌐 teleman.pl",
                    width=100,
                    height=28,
                    font=ctk.CTkFont(size=12),
                    fg_color=pal["surface_elevated"],
                    hover_color=pal["border"],
                    command=lambda l=prog["link"]: webbrowser.open(l),
                )
                btn_link.pack(side="left")

    def _select_program_card(self, prog: dict):
        self.current_selected_prog = prog
        self.current_selected_link = prog.get("link", "")
        self._update_preview_drawer(prog)

    # --- Obsługa wyboru kanałów ---

    def _set_default_channels(self):
        for ch_name, var in self.channel_vars.items():
            var.set(ch_name in DEFAULT_SELECTED_CHANNELS)
        self._update_channel_count()
        self.apply_filters()

    def _select_tvp_only(self):
        for ch_name, var in self.channel_vars.items():
            var.set(ch_name.startswith("TVP"))
        self._update_channel_count()
        self.apply_filters()

    def _select_commercial_only(self):
        for ch_name, var in self.channel_vars.items():
            var.set(not ch_name.startswith("TVP"))
        self._update_channel_count()
        self.apply_filters()

    def _select_all_channels(self):
        for var in self.channel_vars.values():
            var.set(True)
        self._update_channel_count()
        self.apply_filters()

    def _deselect_all_channels(self):
        for var in self.channel_vars.values():
            var.set(False)
        self._update_channel_count()
        self.apply_filters()

    def _on_channel_checkbox_toggled(self):
        self._update_channel_count()
        self.apply_filters()

    def _update_channel_count(self):
        sel_count = sum(1 for v in self.channel_vars.values() if v.get())
        self.ch_count_lbl.configure(text=f"{sel_count} zazn.")
        self.stat_stations_var.set(f"📡 Stacje: {sel_count}")

    def _filter_channel_checkboxes(self):
        q = self.channel_search_var.get().strip().lower()
        for ch_name, (cb, r, c) in self.channel_checkboxes.items():
            if not q or q in ch_name.lower():
                cb.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            else:
                cb.grid_forget()

    # --- Filtry czasowe ---

    def _set_time_preset(self, start_t: str, end_t: str):
        self.entry_from.delete(0, "end")
        self.entry_from.insert(0, start_t)
        self.entry_to.delete(0, "end")
        self.entry_to.insert(0, end_t)
        self.stat_time_var.set(f"⏰ {start_t} – {end_t}")
        self.apply_filters()

    def _set_time_now_plus_3(self):
        now = datetime.now()
        start_t = now.strftime("%H:%M")
        end_t = (now + timedelta(hours=3)).strftime("%H:%M")
        self._set_time_preset(start_t, end_t)

    def _on_time_input_change(self):
        t1 = self.entry_from.get().strip()
        t2 = self.entry_to.get().strip()
        self.stat_time_var.set(f"⏰ {t1} – {t2}")
        self.apply_filters()

    def _on_category_segment_changed(self, choice: str):
        self.apply_filters()

    def _on_date_changed(self, choice: str):
        self.status_var.set(f"Zmieniono dzień na: {choice}. Kliknij 'Pobierz / Odśwież program', aby pobrać dane.")

    # --- Pobieranie danych w tle ---

    def start_fetching_thread(self):
        if self.is_fetching:
            return

        selected_channels = [ch for ch, var in self.channel_vars.items() if var.get()]
        if not selected_channels:
            messagebox.showwarning(
                "Brak stacji",
                "Proszę zaznaczyć przynajmniej jeden kanał przed pobraniem programu.",
            )
            return

        self.is_fetching = True
        self.btn_fetch.configure(state="disabled", text="⏳ Pobieranie stacji...")
        self.progress_bar.set(0)
        self.status_var.set(f"Pobieranie ramówki dla {len(selected_channels)} stacji...")

        thread = threading.Thread(
            target=self._fetch_worker,
            args=(selected_channels, self._get_current_selected_date_slug()),
            daemon=True,
        )
        thread.start()

    def _fetch_worker(self, channels: List[str], date_slug: Optional[str]):
        start_time = datetime.now()

        def on_progress(done: int, total: int, ch_name: str):
            ratio = done / total
            self.after(0, lambda: self._update_progress_ui(ratio, done, total, ch_name))

        try:
            programs = self.scraper.fetch_multiple_channels(
                channels=channels,
                date_str=date_slug,
                progress_callback=on_progress,
            )
            elapsed = (datetime.now() - start_time).total_seconds()
            self.after(0, lambda: self._on_fetch_success(programs, elapsed, len(channels)))
        except Exception as e:
            self.after(0, lambda: self._on_fetch_error(str(e)))

    def _update_progress_ui(self, ratio: float, done: int, total: int, ch_name: str):
        self.progress_bar.set(ratio)
        self.status_var.set(f"Pobieranie ({done}/{total}): {ch_name}...")

    def _on_fetch_success(self, programs: List[dict], elapsed: float, count: int):
        self.all_programs = programs
        self.is_fetching = False
        self.btn_fetch.configure(state="normal", text="⚡ Pobierz / Odśwież program")
        self.progress_bar.set(1.0)
        self.status_var.set(
            f"Pobrano i oceniono {len(programs)} pozycji z {count} stacji w {elapsed:.1f}s."
        )
        self.apply_filters()

    def _on_fetch_error(self, err_msg: str):
        self.is_fetching = False
        self.btn_fetch.configure(state="normal", text="⚡ Pobierz / Odśwież program")
        self.progress_bar.set(0)
        self.status_var.set("Wystąpił błąd podczas pobierania danych.")
        messagebox.showerror("Błąd pobierania", f"Nie udało się pobrać danych:\n{err_msg}")

    # --- Filtracja i Odświeżanie ---

    def apply_filters(self):
        selected_channels = set(ch for ch, var in self.channel_vars.items() if var.get())
        time_from = self.entry_from.get().strip()
        time_to = self.entry_to.get().strip()
        only_movies = ("filmy" in self.category_segmented.get().lower()) and self.only_movies_var.get()
        query = self.search_query_var.get().strip().lower()

        filtered = []
        for prog in self.all_programs:
            if prog["stacja"] not in selected_channels:
                continue

            if only_movies and not prog["is_film"]:
                continue

            if not is_time_in_range(prog["godzina"], time_from, time_to):
                continue

            if query:
                combined = f"{prog['tytul']} {prog['gatunek']} {prog['opis']}".lower()
                if query not in combined:
                    continue

            filtered.append(prog)

        self.filtered_programs = filtered

        # Wyznaczenie medali TOP 3 dla aktualnie przefiltrowanych filmów
        sorted_films = sorted(
            [p for p in filtered if p.get("is_film")],
            key=lambda p: p.get("ranking_pkt", 0.0),
            reverse=True,
        )
        for idx, f in enumerate(sorted_films):
            pkt = f.get("ranking_pkt", 0.0)
            if idx == 0 and pkt >= 70:
                f["ranking_badge"] = f"🥇 {pkt:.1f} pkt"
            elif idx == 1 and pkt >= 65:
                f["ranking_badge"] = f"🥈 {pkt:.1f} pkt"
            elif idx == 2 and pkt >= 60:
                f["ranking_badge"] = f"🥉 {pkt:.1f} pkt"
            else:
                f["ranking_badge"] = f"{pkt:.1f} pkt"

        # Liczniki statystyk KPI
        film_count = sum(1 for p in filtered if p["is_film"])
        self.stat_movies_var.set(f"🎬 Filmy: {film_count}")
        if sorted_films:
            best = sorted_films[0]
            self.stat_top_var.set(f"🏆 Top: {best['tytul'][:22]} ({best.get('ranking_pkt', 0):.1f} pkt)")
        else:
            self.stat_top_var.set("🏆 Top film: —")

        if self.active_view == "karty":
            self._render_cards_view()
        else:
            self._refresh_treeview()

    def _refresh_treeview(self):
        selected_link = self.current_selected_link

        for item in self.tree.get_children():
            self.tree.delete(item)

        self._sort_program_list()

        new_selected_item = None
        for idx, prog in enumerate(self.filtered_programs):
            rank_badge = prog.get("ranking_badge", f"{prog.get('ranking_pkt', 0):.1f} pkt")
            tag = "normal_row"
            if "🍓" in prog.get("wyroznienia", ""):
                tag = "razzie_row"
            elif "🥇" in rank_badge:
                tag = "top_gold"
            elif "🥈" in rank_badge or "🥉" in rank_badge:
                tag = "top_silver"
            elif prog.get("is_film"):
                tag = "film_row"
            elif idx % 2 == 1:
                tag = "alt_row"

            item_id = self.tree.insert(
                "",
                "end",
                values=(
                    rank_badge,
                    prog["godzina"],
                    prog["stacja"],
                    prog["tytul"],
                    prog.get("ocena_glosy", "—"),
                    prog.get("wyroznienia", "—"),
                    prog.get("gatunek", ""),
                    prog["opis"][:120] + ("..." if len(prog["opis"]) > 120 else ""),
                    prog.get("zrodlo", "teleman.pl"),
                ),
                tags=(tag,),
            )

            if prog.get("link") and prog.get("link") == selected_link:
                new_selected_item = item_id

        if new_selected_item:
            self.tree.selection_set(new_selected_item)
            self.tree.see(new_selected_item)

    # --- Sortowanie ---

    def _sort_by_ranking(self):
        self.sort_column = "ranking_pkt"
        self.sort_reverse = True
        self._sort_program_list()
        self._refresh_treeview()
        self.status_var.set("Posortowano według Rankingu (najlepsze pozycje u góry).")

    def _sort_by_time(self):
        self.sort_column = "godzina"
        self.sort_reverse = False
        self._sort_program_list()
        self._refresh_treeview()
        self.status_var.set("Posortowano chronologicznie według Godziny emisji.")

    def _sort_by_column(self, col: str):
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = col in ("ranking_badge", "ranking_pkt")

        for c in self.col_headings:
            base_text = self.col_headings[c]
            if c == self.sort_column:
                arrow = " ▼" if self.sort_reverse else " ▲"
                self.tree.heading(c, text=base_text + arrow)
            else:
                self.tree.heading(c, text=base_text)

        self._refresh_treeview()

    def _sort_program_list(self):
        col = self.sort_column
        rev = self.sort_reverse

        if col in ("ranking_badge", "ranking_pkt"):
            self.filtered_programs.sort(key=lambda p: p.get("ranking_pkt", 0.0), reverse=rev)
        elif col == "godzina":
            def key_func(p):
                m = parse_time_to_minutes(p["godzina"])
                return m if m is not None else -1
            self.filtered_programs.sort(key=key_func, reverse=rev)
        else:
            self.filtered_programs.sort(key=lambda p: str(p.get(col, "")).lower(), reverse=rev)

    # --- Podgląd pozycji ---

    def _on_tree_select(self, _event):
        selected = self.tree.selection()
        if not selected:
            return

        item = self.tree.item(selected[0])
        vals = item.get("values", [])
        if not vals:
            return

        _rank, godzina, stacja, tytul, _ocena, _wyr, _gat, _opis, _zrodlo = vals

        matching = [
            p for p in self.filtered_programs
            if p["godzina"] == godzina and p["stacja"] == stacja and p["tytul"] == tytul
        ]
        if not matching:
            return

        self._update_preview_drawer(matching[0])

    def _update_preview_drawer(self, prog: dict):
        self.current_selected_prog = prog
        self.current_selected_link = prog.get("link", "")

        rank_badge = prog.get("ranking_badge", "")
        movie_icon = "🎬 " if prog["is_film"] else "📺 "
        self.detail_title_lbl.configure(text=f"{movie_icon}{prog['tytul']}")

        rank_str = f"🏆 Indeks Jakości: {prog.get('ranking_pkt', '—')} / 100 pkt"
        if rank_badge:
            rank_str += f"  ({rank_badge})"
        if prog.get("ocena_glosy"):
            rank_str += f"   |   Ocena: {prog['ocena_glosy']}"

        # Czyste nagrody filmowe
        awards = prog.get("nagrody") or prog.get("wyroznienia")
        if awards and awards != "—":
            awards_bonus = prog.get("awards_bonus")
            bonus_str = f" ({awards_bonus:+0.1f} pkt)" if awards_bonus is not None else ""
            rank_str += f"   |   Nagrody: {awards}{bonus_str}"

        # Dodatkowe premie (Nowość, Klasyk, Bez reklam)
        premie = prog.get("premie_info")
        if premie and premie != "—":
            rank_str += f"   |   Premie: {premie}"

        self.detail_rank_lbl.configure(text=rank_str)

        meta_info = f"Kanał: {prog['stacja']}   |   Godzina: {prog['godzina']}   |   Kategoria: {prog['kategoria']}"
        if prog.get("gatunek"):
            meta_info += f"   |   Gatunek: {prog['gatunek']}"
        if prog.get("zrodlo"):
            meta_info += f"   |   Źródło: {prog['zrodlo']}"
        self.detail_meta_lbl.configure(text=meta_info)

        self.detail_desc_box.configure(state="normal")
        self.detail_desc_box.delete("1.0", "end")
        desc_text = prog["opis"] if prog["opis"] else "Brak dodatkowego opisu dla tej pozycji."
        self.detail_desc_box.insert("1.0", desc_text)
        self.detail_desc_box.configure(state="disabled")

        self.btn_open_web.configure(state="normal" if self.current_selected_link else "disabled")
        self.btn_copy_info.configure(state="normal")
        self.btn_trailer.configure(state="normal")

    def _on_tree_double_click(self, event):
        self._on_tree_select(event)
        self._open_in_browser()

    def _open_in_browser(self):
        if self.current_selected_link:
            webbrowser.open(self.current_selected_link)

    def _search_trailer(self):
        if self.current_selected_prog:
            title = self.current_selected_prog["tytul"]
            query = urllib.parse.quote(f"{title} zwiastun trailer")
            webbrowser.open(f"https://www.youtube.com/results?search_query={query}")

    def _copy_selected_info(self):
        if self.current_selected_prog:
            p = self.current_selected_prog
            awards = p.get("nagrody") or p.get("wyroznienia", "—")
            awards_bonus = p.get("awards_bonus")
            bonus_str = f" ({awards_bonus:+0.1f} pkt)" if (awards_bonus is not None and awards != "—") else ""
            premie = p.get("premie_info", "—")
            text = (
                f"{p['tytul']} ({p['stacja']}, {p['godzina']})\n"
                f"Ranking: {p.get('ranking_pkt', '—')} pkt | Ocena: {p.get('ocena_glosy', '—')}\n"
                f"Nagrody: {awards}{bonus_str}\n"
                f"Premie: {premie}\n"
                f"{p['gatunek']}\n\n{p['opis']}\n{p.get('link', '')}"
            )
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("Skopiowano szczegóły filmu z rankingiem do schowka.")

    def _copy_title(self):
        if self.current_selected_prog:
            self.clipboard_clear()
            self.clipboard_append(self.current_selected_prog["tytul"])
            self.status_var.set("Skopiowano tytuł do schowka.")

    # --- Okno dialogowe ustawień API ---

    def _open_api_settings_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Ustawienia kluczy API (OMDb / TMDB)")
        dialog.geometry("540x380")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        pal = THEMES[self.current_theme]
        dialog.configure(fg_color=pal["surface"])

        header_lbl = ctk.CTkLabel(
            dialog,
            text="⚙️ Konfiguracja Ocen i Nagród (OMDb / TMDB)",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=pal["text_primary"],
        )
        header_lbl.pack(pady=(18, 6), padx=20, anchor="w")

        info_lbl = ctk.CTkLabel(
            dialog,
            text=(
                "Aplikacja posiada wbudowaną bazę wiedzy i analizator nagród Telemana,\n"
                "dzięki czemu działa natychmiast bez żadnych kluczy.\n\n"
                "Jeśli posiadasz darmowy klucz OMDb lub TMDB, wklej go poniżej,\n"
                "aby aplikacja automatycznie dociągała dokładne oceny IMDb i liczbę głosów:"
            ),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=pal["text_secondary"],
            justify="left",
        )
        info_lbl.pack(padx=20, pady=(0, 14), anchor="w")

        # OMDb
        omdb_lbl = ctk.CTkLabel(dialog, text="OMDb API Key (darmowy z omdbapi.com):", font=ctk.CTkFont(size=12, weight="bold"))
        omdb_lbl.pack(padx=20, anchor="w")
        omdb_entry = ctk.CTkEntry(dialog, placeholder_text="np. e1234567", width=480, height=32)
        omdb_entry.pack(padx=20, pady=(2, 10))
        omdb_entry.insert(0, self.ranker.config.get("omdb_api_key", ""))

        # TMDB
        tmdb_lbl = ctk.CTkLabel(dialog, text="TMDB API Key (darmowy z themoviedb.org):", font=ctk.CTkFont(size=12, weight="bold"))
        tmdb_lbl.pack(padx=20, anchor="w")
        tmdb_entry = ctk.CTkEntry(dialog, placeholder_text="Klucz API v3 z TMDB", width=480, height=32)
        tmdb_entry.pack(padx=20, pady=(2, 16))
        tmdb_entry.insert(0, self.ranker.config.get("tmdb_api_key", ""))

        btn_row = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 15))

        def save_and_close():
            self.ranker.save_api_keys(omdb_entry.get(), tmdb_entry.get())
            messagebox.showinfo("Zapisano", "Klucze API zostały zapisane w pliku api_config.json.")
            dialog.destroy()

        btn_save = ctk.CTkButton(
            btn_row,
            text="💾 Zapisz konfigurację",
            width=150,
            height=34,
            fg_color=pal["accent"],
            hover_color=pal["accent_hover"],
            command=save_and_close,
        )
        btn_save.pack(side="right")

        btn_cancel = ctk.CTkButton(
            btn_row,
            text="Anuluj",
            width=90,
            height=34,
            fg_color=pal["surface_elevated"],
            hover_color=pal["border"],
            command=dialog.destroy,
        )
        btn_cancel.pack(side="right", padx=(0, 8))

    # --- Eksport CSV ---

    def export_to_csv(self):
        if not self.filtered_programs:
            messagebox.showinfo("Brak danych", "Brak danych do wyeksportowania. Najpierw pobierz program.")
            return

        filename = filedialog.asksaveasfilename(
            title="Zapisz ranking filmów jako CSV",
            defaultextension=".csv",
            filetypes=[("Pliki CSV (*.csv)", "*.csv"), ("Wszystkie pliki", "*.*")],
            initialfile=f"ranking_filmow_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        )
        if not filename:
            return

        try:
            with open(filename, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow([
                    "Miejsce / Ranking",
                    "Punkty (0-100)",
                    "Godzina",
                    "Stacja",
                    "Tytuł",
                    "Ocena (Głosy)",
                    "Nagrody filmowe",
                    "Premie rankingowe",
                    "Gatunek",
                    "Rok",
                    "Opis",
                    "Czy film",
                    "Źródło",
                    "Link"
                ])
                for p in self.filtered_programs:
                    writer.writerow([
                        p.get("ranking_badge", ""),
                        p.get("ranking_pkt", 0.0),
                        p["godzina"],
                        p["stacja"],
                        p["tytul"],
                        p.get("ocena_glosy", ""),
                        p.get("nagrody") or p.get("wyroznienia", "—"),
                        p.get("premie_info", "—"),
                        p.get("gatunek", ""),
                        p.get("rok", ""),
                        p["opis"],
                        "TAK" if p["is_film"] else "NIE",
                        p.get("zrodlo", "teleman.pl"),
                        p.get("link", ""),
                    ])
            self.status_var.set(f"Zapisano {len(self.filtered_programs)} pozycji do: {os.path.basename(filename)}")
            messagebox.showinfo("Eksport zakończony", f"Zapisano ranking {len(self.filtered_programs)} pozycji do pliku:\n{filename}")
        except Exception as e:
            messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać pliku CSV:\n{e}")


if __name__ == "__main__":
    app = TVProgramApp()
    app.mainloop()

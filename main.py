"""
Główny punkt wejścia do aplikacji Program TV.
Uruchamia interfejs graficzny pobierający i filtrujący program telewizyjny z teleman.pl.
"""

import sys
from gui import TVProgramApp


def main():
    try:
        app = TVProgramApp()
        app.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        print(f"Nieoczekiwany błąd aplikacji: {exc}", file=sys.stderr)
        raise exc


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import datetime
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_FILE = BASE_DIR / "data" / "nacional-rfee.json"

RANKING_URL = "https://app.skermo.org/ranking-rfee/public/RFEE"
CALENDAR_URL = "https://app.skermo.org/calendar/public/RFEE"

SEASON_LABEL = "2026-2027"

# En Skermo RFEE, la temporada 2026-2027 utiliza actualmente season=16.
# El script intenta detectarlo automáticamente antes de usar este valor.
DEFAULT_SEASON_ID = "16"

CATEGORY_IDS = {
    "M13": "12",
    "M15": "4",
    "M17": "5",
    "M20": "6",
    "ABS": "7",
}

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "Chrome/120.0 Safari/537.36 "
            "dashboard-sable-femenino/3.0"
        ),
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
)


def read_previous_data():
    """Lee el último JSON válido para utilizarlo como respaldo."""
    if not OUTPUT_FILE.exists():
        return {}

    try:
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"AVISO: no se pudo leer el JSON anterior: {exc}")
        return {}


def get_html(url, params=None):
    """Descarga una página mediante HTTP."""
    response = SESSION.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.text


def get_browser_html(url):
    """
    Abre una página con Chromium cuando Skermo carga la tabla
    mediante JavaScript.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page(
            locale="es-ES",
            viewport={"width": 1440, "height": 1800},
        )

        page.goto(
            url,
            wait_until="networkidle",
            timeout=120000,
        )

        try:
            page.wait_for_selector("table tbody tr", timeout=30000)
        except Exception:
            # Algunas páginas no utilizan tbody.
            page.wait_for_timeout(5000)

        html = page.content()
        browser.close()

    return html


def clean_text(value):
    """Normaliza espacios y saltos de línea."""
    return " ".join(str(value or "").split()).strip()


def table_cells(row):
    return [
        clean_text(cell.get_text(" ", strip=True))
        for cell in row.find_all(["td", "th"])
    ]


def parse_number(value):
    """
    Convierte formatos habituales de Skermo:
    11.268,79 -> 11268.79
    2424 -> 2424.0
    2023.76 -> 2023.76
    """
    text = clean_text(value)
    text = re.sub(r"[^\d,.\-]", "", text)

    if not text:
        return 0.0

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0


def split_name(full_name):
    """
    Mantiene el nombre completo en first_name si no puede determinar
    con seguridad la separación entre nombre y apellidos.
    """
    full_name = clean_text(full_name)

    if not full_name:
        return "", ""

    return full_name, ""


def detect_season_id():
    """
    Detecta el identificador interno que Skermo asigna a 2026-2027.

    Si no se puede detectar, usa el valor comprobado actualmente:
    season=16.
    """
    print(f"Buscando identificador de temporada {SEASON_LABEL}...")

    try:
        html = get_html(
            RANKING_URL,
            params={
                "setLang": "es",
                "weapon": "S",
                "category": CATEGORY_IDS["M15"],
                "gender": "W",
            },
        )

        soup = BeautifulSoup(html, "html.parser")

        for option in soup.select("select option"):
            label = clean_text(option.get_text())

            if SEASON_LABEL in label:
                season_id = clean_text(option.get("value"))

                if season_id:
                    print(
                        f"Temporada {SEASON_LABEL} detectada: "
                        f"season={season_id}"
                    )
                    return season_id

        # Busca también opciones incluidas en scripts o HTML dinámico.
        patterns = [
            rf'value=["\'](\d+)["\'][^>]*>\s*{re.escape(SEASON_LABEL)}',
            rf'{re.escape(SEASON_LABEL)}[^0-9]{{0,30}}["\']?(\d+)["\']?',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)

            if match:
                season_id = match.group(1)
                print(
                    f"Temporada detectada en el código HTML: "
                    f"season={season_id}"
                )
                return season_id

    except Exception as exc:
        print(f"AVISO: no se pudo detectar la temporada: {exc}")

    print(
        f"Se utilizará season={DEFAULT_SEASON_ID} "
        f"para {SEASON_LABEL}."
    )

    return DEFAULT_SEASON_ID


def build_ranking_url(season_id, category_id):
    params = {
        "season": season_id,
        "weapon": "S",
        "category": category_id,
        "gender": "W",
        "setLang": "es",
    }

    return f"{RANKING_URL}?{urlencode(params)}"


def parse_ranking(html):
    """Extrae las filas de una tabla de ranking de Skermo."""
    soup = BeautifulSoup(html, "html.parser")
    ranking = []

    for row in soup.select("table tr"):
        cells = table_cells(row)

        if not cells:
            continue

        # Primera columna: posición, a veces "1" y otras "1."
        position_match = re.search(r"\d+", cells[0])

        if not position_match:
            continue

        position = int(position_match.group())

        if position <= 0:
            continue

        first_name = ""
        last_name = ""
        birth_year = ""
        birth_date = ""
        club = ""
        points = 0.0

        # Formato habitual:
        # Posición | Nombre | Apellidos | Fecha nacimiento | Club | Puntuación
        if len(cells) >= 6:
            first_name = clean_text(cells[1])
            last_name = clean_text(cells[2])
            birth_date = clean_text(cells[3])
            club = clean_text(cells[4])
            points = parse_number(cells[5])

        # Formato alternativo:
        # Posición | Nombre completo | Club | Fecha nacimiento | Puntuación
        elif len(cells) >= 5:
            first_name, last_name = split_name(cells[1])

            if re.search(r"\d{2}/\d{2}/\d{4}", cells[2]):
                birth_date = clean_text(cells[2])
                club = clean_text(cells[3])
            else:
                club = clean_text(cells[2])
                birth_date = clean_text(cells[3])

            points = parse_number(cells[-1])

        else:
            continue

        year_match = re.search(r"(19|20)\d{2}", birth_date)

        if year_match:
            birth_year = year_match.group()

        full_name = clean_text(f"{first_name} {last_name}")

        # Evita incluir cabeceras interpretadas como deportistas.
        if not full_name or full_name.lower() in {
            "nombre",
            "nombre apellidos",
            "apellidos",
        }:
            continue

        ranking.append(
            {
                "position": position,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name,
                "birth_date": birth_date,
                "birth_year": birth_year,
                "club": club,
                "points": points,
            }
        )

    # Elimina duplicados conservando una fila por posición y nombre.
    unique = {}

    for row in ranking:
        key = (
            row["position"],
            row["full_name"].casefold(),
        )
        unique[key] = row

    return sorted(
        unique.values(),
        key=lambda row: (
            row["position"],
            row["full_name"],
        ),
    )


def retrieve_ranking(season_id, category, category_id):
    ranking_url = build_ranking_url(season_id, category_id)

    print(f"Consultando ranking {category}: {ranking_url}")

    ranking = []

    try:
        html = get_html(
            RANKING_URL,
            params={
                "season": season_id,
                "weapon": "S",
                "category": category_id,
                "gender": "W",
                "setLang": "es",
            },
        )

        ranking = parse_ranking(html)

    except Exception as exc:
        print(f"AVISO HTTP {category}: {exc}")

    if not ranking:
        try:
            print(
                f"{category}: tabla no encontrada por HTTP. "
                f"Probando Chromium..."
            )

            html = get_browser_html(ranking_url)
            ranking = parse_ranking(html)

        except Exception as exc:
            print(f"AVISO Chromium {category}: {exc}")

    if not ranking:
        raise RuntimeError(
            f"No se encontraron filas válidas para {category}"
        )

    print(f"{category}: {len(ranking)} tiradoras recuperadas")

    return ranking, ranking_url


def retrieve_all_rankings(season_id, previous_rankings):
    rankings = {}
    ranking_urls = {}

    for category, category_id in CATEGORY_IDS.items():
        try:
            rows, source_url = retrieve_ranking(
                season_id,
                category,
                category_id,
            )

            rankings[category] = rows
            ranking_urls[category] = source_url

        except Exception as exc:
            print(f"AVISO ranking {category}: {exc}")

            old_rows = previous_rankings.get(category, [])

            if old_rows:
                print(
                    f"{category}: se conservan "
                    f"{len(old_rows)} filas anteriores."
                )

            rankings[category] = old_rows
            ranking_urls[category] = build_ranking_url(
                season_id,
                category_id,
            )

    return rankings, ranking_urls


def parse_calendar(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []

    for row in soup.select("table tr"):
        cells = table_cells(row)

        if len(cells) < 5:
            continue

        combined = " ".join(cells).upper()

        if "SABLE" not in combined:
            continue

        if not (
            "FEMENINO" in combined
            or "FEM." in combined
            or " SF " in f" {combined} "
        ):
            continue

        date_match = re.search(
            r"\d{2}/\d{2}/\d{4}",
            combined,
        )

        if not date_match:
            continue

        date = date_match.group()
        name = cells[1] if len(cells) > 1 else "Competición RFEE"

        category = next(
            (
                category_name
                for category_name in [
             "M13",
                    "M15",
                    "M17",
                    "M20",
                    "M23",
                    "ABS",
                ]
                if category_name in combined
            ),
            "ABS",
        )

        modality = (
            "E"
            if "EQUIP" in combined
            else "I"
        )

        scope = (
            "I"
            if any(
                word in combined
                for word in [
                    "FIE",
                    "COPA DEL MUNDO",
                    "GRAND PRIX",
                    "CAMPEONATO DE EUROPA",
                    "CAMPEONATO DEL MUNDO",
                    "SATÉLITE",
                    "SATELITE",
                ]
            )
            else "N"
        )

        link = CALENDAR_URL
        anchor = row.find("a", href=True)

        if anchor:
            link = urljoin(
                CALENDAR_URL,
                anchor.get("href"),
            )

        location = ""

        if len(cells) > 6:
            location = clean_text(cells[6])

        events.append(
            {
                "date": date,
                "name": name,
                "category": category,
                "modality": modality,
                "location": location,
                "type": "Competición RFEE",
                "scope": scope,
                "registration_deadline": "",
                "entries": 0,
                "venue": "",
                "links": [
                    {
                        "label": "Skermo RFEE",
                        "url": link,
                    }
                ],
                "internal_points": [],
            }
        )

    unique = {}

    for event in events:
        key = (
            event["date"],
            event["name"],
            event["category"],
        )
        unique[key] = event

    return list(unique.values())


def retrieve_calendar(previous_calendar):
    params = {
        "setLang": "es",
        "season": DEFAULT_SEASON_ID,
        "weapon": "S",
        "gender": "W",
    }

    calendar_url = f"{CALENDAR_URL}?{urlencode(params)}"

    print(f"Consultando calendario RFEE: {calendar_url}")

    events = []

    try:
        html = get_html(
            CALENDAR_URL,
            params=params,
        )

        events = parse_calendar(html)

    except Exception as exc:
        print(f"AVISO calendario HTTP: {exc}")

    if not events:
        try:
            html = get_browser_html(calendar_url)
            events = parse_calendar(html)

        except Exception as exc:
            print(f"AVISO calendario Chromium: {exc}")

    if not events:
        print(
            "AVISO: no se encontró un calendario nuevo. "
            "Se conserva el anterior."
        )
        return previous_calendar, calendar_url

    print(f"Calendario: {len(events)} pruebas recuperadas")

    return events, calendar_url


def validate_m15(ranking):
    """
    Comprobaciones mínimas para evitar aceptar una temporada incorrecta.
    No exige una deportista concreta porque el ranking acumulado puede
    cambiar después de cada competición.
    """
    if not ranking:
        raise RuntimeError("El ranking M15 está vacío")

    positions = [
        row.get("position")
        for row in ranking
        if isinstance(row.get("position"), int)
    ]

    if not positions:
        raise RuntimeError(
            "El ranking M15 no contiene posiciones válidas"
        )

    if min(positions) != 1:
        raise RuntimeError(
            "El ranking M15 no empieza en la posición 1"
        )

    if max(positions) < 10:
        raise RuntimeError(
            "El ranking M15 contiene menos de 10 posiciones; "
            "posible filtro o temporada incorrectos"
        )

    if not any(
        parse_number(row.get("points")) > 0
        for row in ranking
    ):
        raise RuntimeError(
            "El ranking M15 no contiene puntuaciones válidas"
        )


def main():
    previous = read_previous_data()

    previous_rankings = previous.get("rankings", {})
    previous_calendar = previous.get("calendar", [])
    previous_results = previous.get("results", [])

    season_id = detect_season_id()

    rankings, ranking_urls = retrieve_all_rankings(
        season_id,
        previous_rankings,
    )

    # Una validación defectuosa no debe borrar el ranking anterior.
    try:
        validate_m15(rankings.get("M15", []))
        m15_validation = "ok"

    except Exception as exc:
        print(f"AVISO validación M15: {exc}")
        m15_validation = f"warning: {exc}"

        if previous_rankings.get("M15"):
            rankings["M15"] = previous_rankings["M15"]
            print("M15: restaurado el último ranking válido.")

    calendar, calendar_url = retrieve_calendar(
        previous_calendar
    )

    now = datetime.datetime.now().astimezone()

    output = {
        "updated_at": now.strftime(
            "%d/%m/%Y %H:%M %Z"
        ),
        "source_updated_at": now.isoformat(
            timespec="seconds"
        ),
        "season": {
            "label": SEASON_LABEL,
            "skermo_id": season_id,
        },
        "filters": {
            "weapon": "S",
            "weapon_label": "Sable",
            "gender": "W",
            "gender_label": "Femenino",
        },
        "validation": {
            "M15": m15_validation,
        },
        "ranking_urls": ranking_urls,
        "rankings": rankings,
        "calendar": calendar,
        # Hasta automatizar los resultados detallados, se mantienen
        # los últimos resultados válidos.
        "results": previous_results,
        "sources": [
            {
                "name": "Skermo RFEE · Ranking Nacional",
                "url": RANKING_URL,
                "use": (
                    "Rankings nacionales de Sable Femenino "
                    "por categoría"
                ),
            },
            {
                "name": "Skermo RFEE · Calendario",
                "url": calendar_url,
                "use": (
                    "Calendario nacional de competiciones "
                    "de Sable Femenino"
                ),
            },
        ],
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = OUTPUT_FILE.with_suffix(".json.tmp")

    temporary_file.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Verifica que el JSON escrito puede abrirse antes de reemplazar
    # la versión anterior.
    json.loads(
        temporary_file.read_text(
            encoding="utf-8"
        )
    )

    temporary_file.replace(OUTPUT_FILE)

    print(
        f"Datos RFEE guardados correctamente en "
        f"{OUTPUT_FILE}"
    )

    for category in CATEGORY_IDS:
        print(
            f"{category}: "
            f"{len(rankings.get(category, []))} filas"
        )


if __name__ == "__main__":
    main()

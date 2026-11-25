#!/usr/bin/env python3

import datetime
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

OUTPUT_FILE = (
    BASE_DIR
    / "data"
    / "nacional-rfee.json"
)

RANKING_URL = (
    "https://app.skermo.org/"
    "ranking-rfee/public/RFEE"
)

CALENDAR_URL = (
    "https://app.skermo.org/"
    "calendar/public/RFEE"
)

SEASON_LABEL = "2026-2027"

# Skermo puede cambiar los identificadores internos.
# El script prueba ambos.
SEASON_IDS = [
    "16",
    "17",
]

CATEGORY_IDS = {
    "M13": ["12"],
    "M15": ["4"],
    "M17": ["5"],
    "M20": ["6"],
    "ABS": ["7"],
}

CATEGORY_LABELS = {
    "M13": [
        "M13",
        "Sub 13",
        "Menores de 13",
    ],
    "M15": [
        "M15",
        "Sub 15",
        "Infantil",
        "Menores de 15",
    ],
    "M17": [
        "M17",
        "Sub 17",
        "Cadete",
        "Menores de 17",
    ],
    "M20": [
        "M20",
        "Sub 20",
        "Junior",
        "Júnior",
        "Menores de 20",
    ],
    "ABS": [
        "ABS",
        "Absoluto",
        "Absoluta",
    ],
}

WEAPON_LABELS = [
    "Sable",
    "SABLE",
]

GENDER_LABELS = [
    "Femenino",
    "Femenina",
    "Women",
    "Female",
    "Mujer",
]

CATEGORIES = [
    "M13",
    "M15",
    "M17",
    "M20",
    "ABS",
]


# ============================================================
# TEXTO Y NÚMEROS
# ============================================================

def clean(value):
    return " ".join(
        str(value or "").split()
    ).strip()


def normalize(value):
    """
    Normaliza texto para comparar:
    - minúsculas
    - sin tildes
    - espacios compactados
    """

    text = clean(value).casefold()

    text = "".join(
        character
        for character in unicodedata.normalize(
            "NFD",
            text,
        )
        if unicodedata.category(
            character
        ) != "Mn"
    )

    return text


def parse_number(value):
    """
    Convierte:
    1.234,56 -> 1234.56
    1234,56  -> 1234.56
    1234.56  -> 1234.56
    """

    text = clean(value)

    text = re.sub(
        r"[^0-9,.\-]",
        "",
        text,
    )

    if not text:
        return 0.0

    if (
        "," in text
        and
        "." in text
    ):
        # Formato español 1.234,56
        if text.rfind(",") > text.rfind("."):
            text = (
                text
                .replace(".", "")
                .replace(",", ".")
            )

        # Formato inglés 1,234.56
        else:
            text = text.replace(",", "")

    elif "," in text:
        text = text.replace(
            ",",
            ".",
        )

    try:
        return float(text)

    except ValueError:
        return 0.0


def extract_year(value):
    match = re.search(
        r"(?:19|20)\d{2}",
        clean(value),
    )

    return (
        match.group()
        if match
        else ""
    )


# ============================================================
# JSON ANTERIOR
# ============================================================

def read_previous_data():
    """
    Carga el JSON actual para preservar:
    - ranking anterior válido;
    - ranking interno;
    - resultados;
    - calendario;
    - fuentes.
    """

    if not OUTPUT_FILE.exists():
        return {}

    try:
        return json.loads(
            OUTPUT_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception as error:
        print(
            "AVISO: no se pudo leer "
            "nacional-rfee.json:",
            error,
        )

        return {}


def write_json_safely(data):
    """
    Genera primero un fichero temporal.
    Solo reemplaza el JSON publicado
    después de validar su sintaxis.
    """

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        OUTPUT_FILE
        .with_suffix(".json.tmp")
    )

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    json.loads(
        temporary.read_text(
            encoding="utf-8"
        )
    )

    temporary.replace(
        OUTPUT_FILE
    )


# ============================================================
# PLAYWRIGHT
# ============================================================

def wait_for_page(page):
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=30000,
        )

    except Exception:
        pass

    page.wait_for_timeout(
        1800
    )


def option_matches(
    option_text,
    requested_labels,
):
    option_normalized = normalize(
        option_text
    )

    for requested in requested_labels:
        requested_normalized = normalize(
            requested
        )

        if (
            option_normalized
            ==
            requested_normalized
        ):
            return True

        if (
            requested_normalized
            in
            option_normalized
        ):
            return True

    return False


def select_option_by_labels(
    page,
    labels,
):
    """
    Busca las opciones indicadas en todos
    los selectores de la página.

    Devuelve True cuando selecciona una.
    """

    selects = page.locator(
        "select"
    )

    for select_index in range(
        selects.count()
    ):
        select = selects.nth(
            select_index
        )

        options = select.locator(
            "option"
        )

        for option_index in range(
            options.count()
        ):
            option = options.nth(
                option_index
            )

            option_text = clean(
                option.inner_text()
            )

            if not option_matches(
                option_text,
                labels,
            ):
                continue

            value = option.get_attribute(
                "value"
            )

            try:
                select.select_option(
                    value=value
                )

                wait_for_page(
                    page
                )

                print(
                    "Filtro seleccionado:",
                    option_text,
                )

                return True

            except Exception as error:
                print(
                    "AVISO seleccionando",
                    option_text,
                    error,
                )

    return False


# ============================================================
# IDENTIFICACIÓN DE COLUMNAS
# ============================================================

def find_column(
    headers,
    candidates,
):
    """
    Devuelve el índice de una columna
    comparando los encabezados.
    """

    normalized_headers = [
        normalize(header)
        for header in headers
    ]

    # Primero coincidencia exacta.
    for candidate in candidates:
        target = normalize(
            candidate
        )

        for index, header in enumerate(
            normalized_headers
        ):
            if header == target:
                return index

    # Después coincidencia parcial.
    for candidate in candidates:
        target = normalize(
            candidate
        )

        for index, header in enumerate(
            normalized_headers
        ):
            if target in header:
                return index

    return None


def cell_value(
    cells,
    index,
):
    if index is None:
        return ""

    if index >= len(cells):
        return ""

    return clean(
        cells[index]
    )


# ============================================================
# INTERPRETACIÓN DEL RANKING
# ============================================================

def extract_tables(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    tables = []

    for table in soup.select(
        "table"
    ):
        rows = []

        for tr in table.select(
            "tr"
        ):
            cells = [
                clean(
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                )
                for cell
                in tr.find_all(
                    ["th", "td"]
                )
            ]

            if cells:
                rows.append(
                    cells
                )

        if rows:
            tables.append(
                rows
            )

    return tables


def locate_ranking_table(html):
    """
    Localiza la tabla de ranking por
    los encabezados, no por su posición.
    """

    tables = extract_tables(
        html
    )

    best = None
    best_score = -1

    expected_headers = [
        "posición",
        "posicion",
        "puesto",
        "ranking",
        "nombre",
        "apellidos",
        "club",
        "puntuación",
        "puntuacion",
        "puntos",
    ]

    for table in tables:
        for header_index, row in enumerate(
            table[:10]
        ):
            combined = normalize(
                " ".join(row)
            )

            score = sum(
                1
                for expected
                in expected_headers
                if normalize(expected)
                in combined
            )

            # Bonificación si tiene bastantes filas.
            if len(table) >= 10:
                score += 2

            if score > best_score:
                best_score = score
                best = (
                    table,
                    header_index,
                )

    if not best:
        return None, None

    table, header_index = best

    # Exigimos al menos dos señales
    # semánticas de ranking.
    header_text = normalize(
        " ".join(
            table[header_index]
        )
    )

    semantic_hits = sum(
        1
        for expected in [
            "pos",
            "nombre",
            "club",
            "puntu",
            "puntos",
        ]
        if expected in header_text
    )

    if semantic_hits < 2:
        return None, None

    return table, header_index


def parse_ranking_html(html):
    table, header_index = (
        locate_ranking_table(
            html
        )
    )

    if not table:
        return []

    headers = table[
        header_index
    ]

    position_index = find_column(
        headers,
        [
            "Posición",
            "Posicion",
            "Puesto",
            "Ranking",
            "Pos.",
            "#",
        ],
    )

    first_name_index = find_column(
        headers,
        [
            "Nombre",
        ],
    )

    last_name_index = find_column(
        headers,
        [
            "Apellidos",
            "Apellido",
        ],
    )

    full_name_index = find_column(
        headers,
        [
            "Tiradora",
            "Deportista",
            "Nombre completo",
        ],
    )

    birth_index = find_column(
        headers,
        [
            "Fecha nacimiento",
            "Nacimiento",
            "Año",
            "Ano",
        ],
    )

    club_index = find_column(
        headers,
        [
            "Club",
        ],
    )

    points_index = find_column(
        headers,
        [
            "Puntuación",
            "Puntuacion",
            "Puntos",
            "Total",
        ],
    )

    # Si no identifica posición o puntos
    # no es una tabla de ranking válida.
    if (
        position_index is None
        or
        points_index is None
    ):
        print(
            "AVISO: tabla localizada, "
            "pero no se detectan columnas "
            "Posición/Puntuación."
        )

        print(
            "Encabezados detectados:",
            headers,
        )

        return []

    parsed = []

    for source_row in table[
        header_index + 1:
    ]:
        position_text = cell_value(
            source_row,
            position_index,
        )

        position_match = re.search(
            r"\d+",
            position_text,
        )

        if not position_match:
            continue

        position = int(
            position_match.group()
        )

        first_name = cell_value(
            source_row,
            first_name_index,
        )

        last_name = cell_value(
            source_row,
            last_name_index,
        )

        full_name = cell_value(
            source_row,
            full_name_index,
        )

        # Si no hay columna separada
        # para el nombre completo.
        if not full_name:
            full_name = clean(
                f"{first_name} {last_name}"
            )

        # Algunos formatos tienen todo
        # el nombre en "Nombre".
        if (
            not last_name
            and first_name
        ):
            full_name = first_name

        if not full_name:
            continue

        club = cell_value(
            source_row,
            club_index,
        )

        birth_date = cell_value(
            source_row,
            birth_index,
        )

        points_text = cell_value(
            source_row,
            points_index,
        )

        points = parse_number(
            points_text
        )

        parsed.append(
            {
                "position": position,
                "first_name": (
                    first_name
                    or
                    full_name
                ),
                "last_name": last_name,
                "full_name": full_name,
                "birth_date": birth_date,
                "birth_year": extract_year(
                    birth_date
                ),
                "club": club,
                "points": points,
            }
        )

    # Eliminar duplicados.
    unique = {}

    for row in parsed:
        key = (
            row["position"],
            normalize(
                row["full_name"]
            ),
        )

        unique[key] = row

    rows = sorted(
        unique.values(),
        key=lambda row: (
            row["position"],
            row["full_name"],
        ),
    )

    return rows


# ============================================================
# MÉTODO 1: FILTROS VISIBLES
# ============================================================

def ranking_using_visible_filters(
    browser,
    category,
):
    page = browser.new_page(
        locale="es-ES",
        viewport={
            "width": 1600,
            "height": 2000,
        },
    )

    try:
        page.goto(
            RANKING_URL
            + "?setLang=es",
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_for_page(
            page
        )

        season_ok = select_option_by_labels(
            page,
            [
                SEASON_LABEL,
            ],
        )

        weapon_ok = select_option_by_labels(
            page,
            WEAPON_LABELS,
        )

        category_ok = select_option_by_labels(
            page,
            CATEGORY_LABELS[
                category
            ],
        )

        gender_ok = select_option_by_labels(
            page,
            GENDER_LABELS,
        )

        print(
            category,
            "filtros:",
            {
                "season": season_ok,
                "weapon": weapon_ok,
                "category": category_ok,
                "gender": gender_ok,
            },
        )

        wait_for_page(
            page
        )

        rows = parse_ranking_html(
            page.content()
        )

        return (
            rows,
            page.url,
            page.content(),
        )

    finally:
        page.close()


# ============================================================
# MÉTODO 2: URLS DIRECTAS
# ============================================================

def direct_ranking_urls(
    category,
):
    urls = []

    for season_id in SEASON_IDS:
        for category_id in CATEGORY_IDS[
            category
        ]:
            parameter_sets = [
                {
                    "season": season_id,
                    "weapon": "S",
                    "category": category_id,
                    "gender": "W",
                    "setLang": "es",
                },
                {
                    "season": season_id,
                    "weapon": "S",
                    "category": category_id,
                    "gender": "F",
                    "setLang": "es",
                },
            ]

            for parameters in parameter_sets:
                urls.append(
                    RANKING_URL
                    + "?"
                    + urlencode(
                        parameters
                    )
                )

    return urls


def ranking_using_direct_urls(
    browser,
    category,
):
    last_html = ""

    for url in direct_ranking_urls(
        category
    ):
        print(
            "Probando URL:",
            url,
        )

        page = browser.new_page(
            locale="es-ES",
            viewport={
                "width": 1600,
                "height": 2000,
            },
        )

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=120000,
            )

            wait_for_page(
                page
            )

            html = page.content()
            last_html = html

            rows = parse_ranking_html(
                html
            )

            if rows:
                return (
                    rows,
                    page.url,
                    html,
                )

        except Exception as error:
            print(
                "AVISO URL directa:",
                error,
            )

        finally:
            page.close()

    return (
        [],
        RANKING_URL,
        last_html,
    )


# ============================================================
# RECUPERAR UNA CATEGORÍA
# ============================================================

def retrieve_category(
    browser,
    category,
    previous_rows,
):
    print()
    print(
        "=============================="
    )

    print(
        "Actualizando",
        category,
    )

    print(
        "=============================="
    )

    rows = []
    source_url = RANKING_URL
    diagnostic_html = ""

    # Método 1.
    try:
        (
            rows,
            source_url,
            diagnostic_html,
        ) = ranking_using_visible_filters(
            browser,
            category,
        )

    except Exception as error:
        print(
            "AVISO filtros visibles",
            category,
            error,
        )

    # Método 2.
    if not rows:
        try:
            (
                rows,
                source_url,
                direct_html,
            ) = ranking_using_direct_urls(
                browser,
                category,
            )

            if direct_html:
                diagnostic_html = (
                    direct_html
                )

        except Exception as error:
            print(
                "AVISO URLs directas",
                category,
                error,
            )

    # Guardar diagnóstico si no se extrajo.
    if not rows and diagnostic_html:
        diagnostic_path = Path(
            f"/tmp/skermo-{category}.html"
        )

        diagnostic_path.write_text(
            diagnostic_html,
            encoding="utf-8",
        )

        print(
            "HTML diagnóstico:",
            diagnostic_path,
        )

    if rows:
        positive = sum(
            row["points"] > 0
            for row in rows
        )

        maximum = max(
            (
                row["points"]
                for row in rows
            ),
            default=0,
        )

        print(
            category,
            ":",
            len(rows),
            "filas",
        )

        print(
            category,
            ":",
            positive,
            "puntuaciones positivas",
        )

        print(
            category,
            ": máximo",
            maximum,
        )

        # Protección específica.
        if (
            category == "M15"
            and positive == 0
        ):
            print(
                "AVISO: M15 extraído, "
                "pero todos los puntos "
                "son cero."
            )

            rows = []

    # Usar anterior solo si realmente
    # contiene filas.
    if not rows and previous_rows:
        print(
            category,
            ": se conservan",
            len(previous_rows),
            "filas anteriores.",
        )

        return (
            previous_rows,
            source_url,
            "previous",
        )

    if not rows:
        print(
            category,
            ": no se pudo recuperar "
            "ningún ranking válido.",
        )

        return (
            [],
            source_url,
            "empty",
        )

    return (
        rows,
        source_url,
        "live",
    )


# ============================================================
# CALENDARIO
# ============================================================

def parse_calendar_html(html):
    tables = extract_tables(
        html
    )

    events = []

    for table in tables:
        for row in table:
            combined = normalize(
                " ".join(row)
            )

            if "sable" not in combined:
                continue

            if not any(
                value in combined
                for value in [
                    "femenino",
                    "femenina",
                    "women",
                ]
            ):
                continue

            date = next(
                (
                    clean(cell)
                    for cell in row
                    if re.search(
                        r"\d{2}/\d{2}/\d{4}",
                        clean(cell),
                    )
                ),
                "",
            )

            date_match = re.search(
                r"\d{2}/\d{2}/\d{4}",
                date,
            )

            if not date_match:
                continue

            event_date = date_match.group()

            name = (
                row[1]
                if len(row) > 1
                else "Competición RFEE"
            )

            category = next(
                (
                    category_name
                    for category_name
                    in CATEGORIES
                    if normalize(
                        category_name
                    )
                    in combined
                ),
                "ABS",
            )

            location = (
                row[6]
                if len(row) > 6
                else ""
            )

            events.append(
                {
                    "date": event_date,
                    "name": clean(name),
                    "category": category,
                    "modality": (
                        "E"
                        if "equip" in combined
                        else "I"
                    ),
                    "location": clean(
                        location
                    ),
                    "type": (
                        "Competición RFEE"
                    ),
                    "scope": (
                        "I"
                        if any(
                            word in combined
                            for word in [
                                "fie",
                                "mundial",
                                "europeo",
                                "grand prix",
                                "copa del mundo",
                            ]
                        )
                        else "N"
                    ),
                    "registration_deadline": "",
                    "links": [
                        {
                            "label": (
                                "Calendario RFEE"
                            ),
                            "url": CALENDAR_URL,
                        }
                    ],
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

    return list(
        unique.values()
    )


def retrieve_calendar(
    browser,
    previous_calendar,
):
    page = browser.new_page(
        locale="es-ES",
        viewport={
            "width": 1600,
            "height": 2000,
        },
    )

    try:
        page.goto(
            CALENDAR_URL
            + "?setLang=es",
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_for_page(
            page
        )

        select_option_by_labels(
            page,
            [SEASON_LABEL],
        )

        select_option_by_labels(
            page,
            WEAPON_LABELS,
        )

        select_option_by_labels(
            page,
            GENDER_LABELS,
        )

        wait_for_page(
            page
        )

        events = parse_calendar_html(
            page.content()
        )

        if events:
            print(
                "Calendario:",
                len(events),
                "eventos",
            )

            return (
                events,
                page.url,
            )

        print(
            "AVISO: calendario RFEE "
            "vacío. Se conserva el "
            "anterior."
        )

        return (
            previous_calendar,
            page.url,
        )

    except Exception as error:
        print(
            "AVISO calendario RFEE:",
            error,
        )

        return (
            previous_calendar,
            CALENDAR_URL,
        )

    finally:
        page.close()


# ============================================================
# VALIDACIÓN
# ============================================================

def validate_m15(rankings):
    m15 = rankings.get(
        "M15",
        [],
    )

    rows = len(
        m15
    )

    positive = sum(
        parse_number(
            row.get(
                "points",
                0,
            )
        )
        > 0
        for row in m15
    )

    maximum = max(
        (
            parse_number(
                row.get(
                    "points",
                    0,
                )
            )
            for row in m15
        ),
        default=0,
    )

    validation = {
        "M15_rows": rows,
        "M15_positive_points": positive,
        "M15_max_points": maximum,
    }

    if rows == 0:
        raise RuntimeError(
            "M15 está vacío. "
            "Skermo no devolvió una "
            "tabla válida y no existe "
            "un ranking M15 anterior "
            "que conservar."
        )

    if positive == 0:
        raise RuntimeError(
            "M15 contiene tiradoras, "
            "pero todos los puntos "
            "son cero."
        )

    return validation


# ============================================================
# FUENTES
# ============================================================

def merge_sources(previous_sources):
    required = [
        {
            "name": (
                "Skermo RFEE · "
                "Ranking Nacional"
            ),
            "url": (
                RANKING_URL
                + "?setLang=es"
            ),
            "use": (
                "Rankings nacionales "
                "de Sable Femenino"
            ),
        },
        {
            "name": (
                "Skermo RFEE · "
                "Calendario"
            ),
            "url": (
                CALENDAR_URL
                + "?setLang=es"
            ),
            "use": (
                "Calendario RFEE "
                "de Sable Femenino"
            ),
        },
    ]

    result = []
    seen = set()

    for source in (
        list(previous_sources or [])
        +
        required
    ):
        url = source.get(
            "url",
            "",
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(
            url
        )

        result.append(
            source
        )

    return result


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    previous = read_previous_data()

    previous_rankings = (
        previous.get(
            "rankings",
            {},
        )
    )

    previous_calendar = (
        previous.get(
            "calendar",
            [],
        )
    )

    rankings = {}
    ranking_urls = {}
    ranking_status = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        for category in CATEGORIES:
            (
                rows,
                source_url,
                status,
            ) = retrieve_category(
                browser,
                category,
                previous_rankings.get(
                    category,
                    [],
                ),
            )

            rankings[category] = rows
            ranking_urls[category] = (
                source_url
            )
            ranking_status[category] = (
                status
            )

        (
            calendar,
            calendar_url,
        ) = retrieve_calendar(
            browser,
            previous_calendar,
        )

        browser.close()

    validation = validate_m15(
        rankings
    )

    now = (
        datetime.datetime
        .now()
        .astimezone()
    )

    # Empezar desde el JSON anterior
    # permite preservar:
    # - internal_rankings
    # - internal_rankings_status
    # - resultados
    # - cualquier metadato añadido.
    output = dict(
        previous
    )

    output.update(
        {
            "updated_at": (
                now.strftime(
                    "%d/%m/%Y %H:%M %Z"
                )
            ),
            "source_updated_at": (
                now.isoformat(
                    timespec="seconds"
                )
            ),
            "season": SEASON_LABEL,
            "filters": {
                "weapon": "Sable",
                "gender": "Femenino",
            },
            "validation": validation,
            "ranking_status": (
                ranking_status
            ),
            "ranking_urls": (
                ranking_urls
            ),
            "rankings": rankings,
            "calendar_url": (
                calendar_url
            ),
            "calendar": calendar,
            "sources": merge_sources(
                previous.get(
                    "sources",
                    [],
                )
            ),
        }
    )

    # Conservar resultados anteriores.
    output.setdefault(
        "results",
        previous.get(
            "results",
            [],
        ),
    )

    write_json_safely(
        output
    )

    print()
    print(
        "================================"
    )

    print(
        "ACTUALIZACIÓN RFEE COMPLETADA"
    )

    print(
        "================================"
    )

    for category in CATEGORIES:
        rows = rankings.get(
            category,
            [],
        )

        positives = sum(
            parse_number(
                row.get(
                    "points",
                    0,
                )
            )
            > 0
            for row in rows
        )

        print(
            category,
            ":",
            len(rows),
            "filas,",
            positives,
            "con puntos,",
            "estado:",
            ranking_status.get(
                category
            ),
        )

    print()
    print(
        "Validación M15:",
        validation,
    )

    print()
    print(
        "Ranking interno preservado:",
        bool(
            output.get(
                "internal_rankings"
            )
        ),
    )

    print()
    print(
        "Archivo guardado:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import datetime
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

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

CATEGORIES = [
    "M13",
    "M15",
    "M17",
    "M20",
    "ABS",
]

CATEGORY_LABELS = {
    "M13": [
        "M13",
        "Sub 13",
        "Sub-13",
        "Menores de 13",
    ],
    "M15": [
        "M15",
        "Sub 15",
        "Sub-15",
        "Infantil",
        "Menores de 15",
    ],
    "M17": [
        "M17",
        "Sub 17",
        "Sub-17",
        "Cadete",
        "Menores de 17",
    ],
    "M20": [
        "M20",
        "Sub 20",
        "Sub-20",
        "Junior",
        "Júnior",
        "Menores de 20",
    ],
    "ABS": [
        "ABS",
        "Absoluto",
        "Absoluta",
        "Senior",
        "Sénior",
    ],
}

WEAPON_LABELS = [
    "Sable",
]

GENDER_LABELS = [
    "Femenino",
    "Femenina",
    "Women",
    "Female",
]

SEASON_PARAMETER_NAMES = [
    "season",
    "season_id",
    "idSeason",
]

WEAPON_PARAMETER_NAMES = [
    "weapon",
    "weapon_id",
    "idWeapon",
]

CATEGORY_PARAMETER_NAMES = [
    "category",
    "category_id",
    "idCategory",
]

GENDER_PARAMETER_NAMES = [
    "gender",
    "gender_id",
    "idGender",
]

TABLE_REQUIRED_HEADERS = [
    [
        "posición",
        "posicion",
        "puesto",
        "ranking",
        "pos.",
        "#",
    ],
    [
        "nombre",
        "tiradora",
        "deportista",
    ],
    [
        "puntuación",
        "puntuacion",
        "puntos",
        "total",
    ],
]

# Comprobación solicitada a partir del ranking oficial actual.
EXPECTED_M15_LEADERS = [
    "ADRIANA VICENTE MORENO",
    "ANNA GALLEGO AGUSTI",
]


# ============================================================
# UTILIDADES DE TEXTO
# ============================================================

def clean(value):
    return " ".join(
        str(value or "").split()
    ).strip()


def normalize(value):
    text = clean(value).casefold()

    text = "".join(
        character
        for character in unicodedata.normalize(
            "NFD",
            text,
        )
        if unicodedata.category(
            character
        )
        !=
        "Mn"
    )

    return text


def compact_name(value):
    """
    Normaliza nombres para comparar:
    - mayúsculas/minúsculas;
    - tildes;
    - signos;
    - espacios.
    """

    text = normalize(value)

    text = re.sub(
        r"[^a-z0-9 ]",
        " ",
        text,
    )

    return " ".join(
        text.split()
    ).upper()


def parse_number(value):
    text = re.sub(
        r"[^0-9,.\-]",
        "",
        clean(value),
    )

    if not text:
        return 0.0

    if "," in text and "." in text:

        if text.rfind(",") > text.rfind("."):
            text = (
                text
                .replace(".", "")
                .replace(",", ".")
            )

        else:
            text = text.replace(
                ",",
                "",
            )

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
            "el JSON nacional anterior:",
            error,
        )

        return {}


def write_json_safely(data):
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


def save_diagnostic(
    category,
    name,
    content,
):
    path = Path(
        f"/tmp/rfee-{category}-{name}.html"
    )

    path.write_text(
        content,
        encoding="utf-8",
    )

    print(
        "Diagnóstico guardado:",
        path,
    )


# ============================================================
# DESCUBRIR LOS DESPLEGABLES REALES
# ============================================================

def get_select_definitions(page):
    """
    Lee todos los desplegables y devuelve:
    - name;
    - id;
    - opciones;
    - valor seleccionado.
    """

    definitions = []

    selects = page.locator(
        "select"
    )

    for select_index in range(
        selects.count()
    ):
        select = selects.nth(
            select_index
        )

        name = clean(
            select.get_attribute(
                "name"
            )
        )

        element_id = clean(
            select.get_attribute(
                "id"
            )
        )

        value = clean(
            select.input_value()
        )

        options = []

        option_locator = (
            select.locator(
                "option"
            )
        )

        for option_index in range(
            option_locator.count()
        ):
            option = (
                option_locator.nth(
                    option_index
                )
            )

            options.append(
                {
                    "text": clean(
                        option.inner_text()
                    ),
                    "value": clean(
                        option.get_attribute(
                            "value"
                        )
                    ),
                    "selected": (
                        option.is_checked()
                        if (
                            option.get_attribute(
                                "selected"
                            )
                            is not None
                        )
                        else False
                    ),
                }
            )

        definitions.append(
            {
                "index": select_index,
                "name": name,
                "id": element_id,
                "value": value,
                "options": options,
            }
        )

    return definitions


def labels_match(
    visible_text,
    requested_labels,
):
    visible = normalize(
        visible_text
    )

    for label in requested_labels:
        requested = normalize(
            label
        )

        if visible == requested:
            return True

        if (
            requested
            and
            requested in visible
        ):
            return True

    return False


def find_option_in_definitions(
    definitions,
    labels,
):
    """
    Busca una opción por texto visible y
    devuelve el selector y el valor real.
    """

    exact_matches = []
    partial_matches = []

    for definition in definitions:
        for option in definition[
            "options"
        ]:
            visible = normalize(
                option["text"]
            )

            for label in labels:
                requested = normalize(
                    label
                )

                if not requested:
                    continue

                match = {
                    "select_index": (
                        definition[
                            "index"
                        ]
                    ),
                    "select_name": (
                        definition[
                            "name"
                        ]
                    ),
                    "select_id": (
                        definition[
                            "id"
                        ]
                    ),
                    "option_text": (
                        option[
                            "text"
                        ]
                    ),
                    "option_value": (
                        option[
                            "value"
                        ]
                    ),
                }

                if visible == requested:
                    exact_matches.append(
                        match
                    )

                elif requested in visible:
                    partial_matches.append(
                        match
                    )

    matches = (
        exact_matches
        or
        partial_matches
    )

    return (
        matches[0]
        if matches
        else None
    )


def parameter_name_for_match(
    match,
    default_names,
):
    if match["select_name"]:
        return match["select_name"]

    if match["select_id"]:
        return match["select_id"]

    return default_names[0]


def discover_filter_values(
    page,
    category,
):
    definitions = (
        get_select_definitions(
            page
        )
    )

    print(
        "Desplegables detectados:"
    )

    for definition in definitions:
        print(
            {
                "name": definition[
                    "name"
                ],
                "id": definition[
                    "id"
                ],
                "value": definition[
                    "value"
                ],
                "options": [
                    option["text"]
                    for option
                    in definition[
                        "options"
                    ]
                ],
            }
        )

    season = find_option_in_definitions(
        definitions,
        [SEASON_LABEL],
    )

    weapon = find_option_in_definitions(
        definitions,
        WEAPON_LABELS,
    )

    category_match = (
        find_option_in_definitions(
            definitions,
            CATEGORY_LABELS[
                category
            ],
        )
    )

    gender = find_option_in_definitions(
        definitions,
        GENDER_LABELS,
    )

    missing = []

    if not season:
        missing.append(
            "temporada "
            + SEASON_LABEL
        )

    if not weapon:
        missing.append(
            "arma Sable"
        )

    if not category_match:
        missing.append(
            "categoría "
            + category
        )

    if not gender:
        missing.append(
            "género Femenino"
        )

    if missing:
        raise RuntimeError(
            "No se han encontrado "
            "estos filtros: "
            + ", ".join(missing)
        )

    return {
        parameter_name_for_match(
            season,
            SEASON_PARAMETER_NAMES,
        ): season[
            "option_value"
        ],
        parameter_name_for_match(
            weapon,
            WEAPON_PARAMETER_NAMES,
        ): weapon[
            "option_value"
        ],
        parameter_name_for_match(
            category_match,
            CATEGORY_PARAMETER_NAMES,
        ): category_match[
            "option_value"
        ],
        parameter_name_for_match(
            gender,
            GENDER_PARAMETER_NAMES,
        ): gender[
            "option_value"
        ],
        "setLang": "es",
    }, {
        "season": {
            "text": season[
                "option_text"
            ],
            "value": season[
                "option_value"
            ],
        },
        "weapon": {
            "text": weapon[
                "option_text"
            ],
            "value": weapon[
                "option_value"
            ],
        },
        "category": {
            "text": category_match[
                "option_text"
            ],
            "value": category_match[
                "option_value"
            ],
        },
        "gender": {
            "text": gender[
                "option_text"
            ],
            "value": gender[
                "option_value"
            ],
        },
    }


# ============================================================
# URL DE CONSULTA
# ============================================================

def create_url(
    base_url,
    parameters,
):
    split = urlsplit(
        base_url
    )

    current_parameters = dict(
        parse_qsl(
            split.query,
            keep_blank_values=True,
        )
    )

    current_parameters.update(
        parameters
    )

    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(
                current_parameters
            ),
            split.fragment,
        )
    )


# ============================================================
# VALIDACIÓN DE FILTROS VISIBLES
# ============================================================

def selected_option_texts(page):
    selected = []

    selects = page.locator(
        "select"
    )

    for index in range(
        selects.count()
    ):
        select = selects.nth(
            index
        )

        try:
            value = select.input_value()

            selected_option = (
                select.locator(
                    f'option[value="{value}"]'
                )
            )

            if (
                selected_option.count()
                >
                0
            ):
                selected.append(
                    clean(
                        selected_option
                        .first
                        .inner_text()
                    )
                )

        except Exception:
            continue

    return selected


def verify_selected_filters(
    page,
    category,
):
    selected = (
        selected_option_texts(
            page
        )
    )

    print(
        category,
        "opciones seleccionadas:",
        selected,
    )

    checks = {
        "season": any(
            labels_match(
                value,
                [SEASON_LABEL],
            )
            for value in selected
        ),
        "weapon": any(
            labels_match(
                value,
                WEAPON_LABELS,
            )
            for value in selected
        ),
        "category": any(
            labels_match(
                value,
                CATEGORY_LABELS[
                    category
                ],
            )
            for value in selected
        ),
        "gender": any(
            labels_match(
                value,
                GENDER_LABELS,
            )
            for value in selected
        ),
    }

    print(
        category,
        "validación de filtros:",
        checks,
    )

    if not all(
        checks.values()
    ):
        raise RuntimeError(
            "La página no confirma todos "
            "los filtros esperados: "
            + json.dumps(
                checks,
                ensure_ascii=False,
            )
        )

    return selected


# ============================================================
# TABLAS HTML
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
                for cell in tr.find_all(
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


def find_column(
    headers,
    candidates,
):
    normalized_headers = [
        normalize(header)
        for header in headers
    ]

    for candidate in candidates:
        requested = normalize(
            candidate
        )

        for index, header in enumerate(
            normalized_headers
        ):
            if header == requested:
                return index

    for candidate in candidates:
        requested = normalize(
            candidate
        )

        for index, header in enumerate(
            normalized_headers
        ):
            if requested in header:
                return index

    return None


def cell(
    row,
    index,
):
    if index is None:
        return ""

    if index >= len(row):
        return ""

    return clean(
        row[index]
    )


def headers_are_ranking(
    headers,
):
    """
    Exige tres grupos:
    - posición;
    - nombre o deportista;
    - puntuación o puntos.
    """

    normalized_headers = [
        normalize(header)
        for header in headers
    ]

    for required_group in (
        TABLE_REQUIRED_HEADERS
    ):
        found = False

        for candidate in required_group:
            requested = normalize(
                candidate
            )

            if any(
                requested == header
                or
                requested in header
                for header
                in normalized_headers
            ):
                found = True
                break

        if not found:
            return False

    return True


def find_ranking_table(html):
    tables = extract_tables(
        html
    )

    candidates = []

    for table_index, table in enumerate(
        tables
    ):
        for header_index, headers in enumerate(
            table[:10]
        ):
            if not headers_are_ranking(
                headers
            ):
                continue

            data_rows = (
                table[
                    header_index + 1:
                ]
            )

            numeric_rows = sum(
                1
                for row in data_rows
                if (
                    row
                    and
                    re.search(
                        r"\d+",
                        row[0],
                    )
                )
            )

            candidates.append(
                {
                    "table_index": (
                        table_index
                    ),
                    "header_index": (
                        header_index
                    ),
                    "headers": headers,
                    "table": table,
                    "numeric_rows": (
                        numeric_rows
                    ),
                }
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["numeric_rows"],
            len(item["table"]),
        ),
        reverse=True,
    )

    selected = candidates[0]

    print(
        "Tabla de ranking seleccionada:",
        {
            "table_index": (
                selected[
                    "table_index"
                ]
            ),
            "header_index": (
                selected[
                    "header_index"
                ]
            ),
            "headers": (
                selected[
                    "headers"
                ]
            ),
            "numeric_rows": (
                selected[
                    "numeric_rows"
                ]
            ),
        },
    )

    return selected


# ============================================================
# PARSEAR RANKING
# ============================================================

def parse_ranking(
    html,
):
    selected = find_ranking_table(
        html
    )

    if not selected:
        return [], []

    table = selected[
        "table"
    ]

    header_index = selected[
        "header_index"
    ]

    headers = selected[
        "headers"
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

    name_index = find_column(
        headers,
        [
            "Nombre",
        ],
    )

    surname_index = find_column(
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

    club_index = find_column(
        headers,
        [
            "Club",
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

    points_index = find_column(
        headers,
        [
            "Puntuación",
            "Puntuacion",
            "Puntos",
            "Total",
        ],
    )

    if (
        position_index is None
        or
        points_index is None
    ):
        return [], headers

    rows = []

    for source_row in table[
        header_index + 1:
    ]:
        position_text = cell(
            source_row,
            position_index,
        )

        match = re.search(
            r"\d+",
            position_text,
        )

        if not match:
            continue

        position = int(
            match.group()
        )

        first_name = cell(
            source_row,
            name_index,
        )

        last_name = cell(
            source_row,
            surname_index,
        )

        combined_name = cell(
            source_row,
            full_name_index,
        )

        if not combined_name:
            combined_name = clean(
                f"{first_name} "
                f"{last_name}"
            )

        if (
            combined_name
            and
            not first_name
        ):
            first_name = (
                combined_name
            )

        if not combined_name:
            continue

        club = cell(
            source_row,
            club_index,
        )

        birth_date = cell(
            source_row,
            birth_index,
        )

        points = parse_number(
            cell(
                source_row,
                points_index,
            )
        )

        rows.append(
            {
                "position": position,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": (
                    combined_name
                ),
                "birth_date": birth_date,
                "birth_year": (
                    extract_year(
                        birth_date
                    )
                ),
                "club": club,
                "points": points,
            }
        )

    unique = {}

    for row in rows:
        key = (
            row["position"],
            compact_name(
                row["full_name"]
            ),
        )

        unique[key] = row

    result = sorted(
        unique.values(),
        key=lambda row: (
            row["position"],
            compact_name(
                row["full_name"]
            ),
        ),
    )

    return result, headers


# ============================================================
# VALIDACIONES POR CATEGORÍA
# ============================================================

def validate_positions(rows):
    if not rows:
        raise RuntimeError(
            "La tabla no contiene filas"
        )

    positions = [
        row["position"]
        for row in rows
    ]

    if min(positions) != 1:
        raise RuntimeError(
            "El ranking no comienza "
            "en la posición 1"
        )

    if len(set(positions)) < 2:
        raise RuntimeError(
            "El ranking no contiene "
            "suficientes posiciones"
        )


def validate_points(rows):
    positive = sum(
        row["points"] > 0
        for row in rows
    )

    if positive == 0:
        raise RuntimeError(
            "Todas las puntuaciones "
            "son cero"
        )

    return positive


def validate_m15_leaders(rows):
    if len(rows) < 2:
        raise RuntimeError(
            "M15 contiene menos "
            "de dos tiradoras"
        )

    actual = [
        compact_name(
            rows[0]["full_name"]
        ),
        compact_name(
            rows[1]["full_name"]
        ),
    ]

    expected = [
        compact_name(name)
        for name in (
            EXPECTED_M15_LEADERS
        )
    ]

    if actual != expected:
        raise RuntimeError(
            "M15 no coincide con el "
            "ranking oficial esperado. "
            f"Primeras extraídas: {actual}. "
            f"Esperadas: {expected}."
        )


def validate_category(
    category,
    rows,
):
    validate_positions(
        rows
    )

    positive = validate_points(
        rows
    )

    if category == "M15":
        validate_m15_leaders(
            rows
        )

    return {
        "rows": len(rows),
        "positive_points": positive,
        "maximum_points": max(
            row["points"]
            for row in rows
        ),
        "first_two": [
            row["full_name"]
            for row in rows[:2]
        ],
    }


# ============================================================
# OBTENER RANKING CORRECTO
# ============================================================

def discover_parameters(
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

        parameters, selection = (
            discover_filter_values(
                page,
                category,
            )
        )

        return (
            parameters,
            selection,
        )

    finally:
        page.close()


def retrieve_live_ranking(
    browser,
    category,
):
    parameters, expected_selection = (
        discover_parameters(
            browser,
            category,
        )
    )

    query_url = create_url(
        RANKING_URL,
        parameters,
    )

    print(
        category,
        "URL construida:",
        query_url,
    )

    print(
        category,
        "selección esperada:",
        expected_selection,
    )

    page = browser.new_page(
        locale="es-ES",
        viewport={
            "width": 1600,
            "height": 2200,
        },
    )

    try:
        page.goto(
            query_url,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_for_page(
            page
        )

        selected_options = (
            verify_selected_filters(
                page,
                category,
            )
        )

        html = page.content()

        rows, table_headers = (
            parse_ranking(
                html
            )
        )

        try:
            validation = (
                validate_category(
                    category,
                    rows,
                )
            )

        except Exception:
            save_diagnostic(
                category,
                "invalid",
                html,
            )

            raise

        return {
            "rows": rows,
            "url": page.url,
            "selection": (
                expected_selection
            ),
            "selected_options": (
                selected_options
            ),
            "table_headers": (
                table_headers
            ),
            "validation": validation,
        }

    finally:
        page.close()


# ============================================================
# CALENDARIO
# ============================================================

def parse_calendar(html):
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

            if not (
                "femenino" in combined
                or
                "femenina" in combined
            ):
                continue

            date = ""

            for value in row:
                match = re.search(
                    r"\d{2}/\d{2}/\d{4}",
                    clean(value),
                )

                if match:
                    date = match.group()
                    break

            if not date:
                continue

            name = (
                clean(row[1])
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

            events.append(
                {
                    "date": date,
                    "name": name,
                    "category": category,
                    "modality": (
                        "E"
                        if "equip" in combined
                        else "I"
                    ),
                    "location": (
                        clean(row[6])
                        if len(row) > 6
                        else ""
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

        events = parse_calendar(
            page.content()
        )

        if events:
            return events, page.url

        print(
            "AVISO: calendario nacional "
            "vacío; se conserva el anterior."
        )

        return (
            previous_calendar,
            page.url,
        )

    except Exception as error:
        print(
            "AVISO calendario:",
            error,
        )

        return (
            previous_calendar,
            CALENDAR_URL,
        )

    finally:
        page.close()


# ============================================================
# FUENTES
# ============================================================

def merge_sources(
    current_sources,
):
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

    merged = []
    seen = set()

    for source in (
        list(current_sources or [])
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

        merged.append(
            source
        )

    return merged


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

    rankings = {}
    ranking_urls = {}
    ranking_status = {}
    ranking_selections = {}
    ranking_headers = {}
    category_validations = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True
        )

        for category in CATEGORIES:
            print()
            print(
                "================================"
            )
            print(
                "ACTUALIZANDO",
                category,
            )
            print(
                "================================"
            )

            try:
                result = (
                    retrieve_live_ranking(
                        browser,
                        category,
                    )
                )

                rankings[category] = (
                    result["rows"]
                )

                ranking_urls[category] = (
                    result["url"]
                )

                ranking_status[category] = (
                    "live"
                )

                ranking_selections[category] = {
                    "season": (
                        result[
                            "selection"
                        ][
                            "season"
                        ]
                    ),
                    "weapon": (
                        result[
                            "selection"
                        ][
                            "weapon"
                        ]
                    ),
                    "category": (
                        result[
                            "selection"
                        ][
                            "category"
                        ]
                    ),
                    "gender": (
                        result[
                            "selection"
                        ][
                            "gender"
                        ]
                    ),
                    "selected_options": (
                        result[
                            "selected_options"
                        ]
                    ),
                }

                ranking_headers[category] = (
                    result[
                        "table_headers"
                    ]
                )

                category_validations[category] = (
                    result[
                        "validation"
                    ]
                )

                print(
                    category,
                    "VALIDADO:",
                    result["validation"],
                )

            except Exception as error:
                print(
                    "ERROR",
                    category,
                    ":",
                    error,
                )

                old_rows = (
                    previous_rankings.get(
                        category,
                        [],
                    )
                )

                # No conservamos M13/M15 si no
                # podemos confirmar que son correctos.
                if (
                    category in [
                        "M13",
                        "M15",
                    ]
                ):
                    rankings[category] = []
                    ranking_status[category] = (
                        "rejected"
                    )

                elif old_rows:
                    rankings[category] = (
                        old_rows
                    )
                    ranking_status[category] = (
                        "previous"
                    )

                else:
                    rankings[category] = []
                    ranking_status[category] = (
                        "empty"
                    )

                ranking_urls[category] = (
                    RANKING_URL
                    + "?setLang=es"
                )

        (
            calendar,
            calendar_url,
        ) = retrieve_calendar(
            browser,
            previous.get(
                "calendar",
                [],
            ),
        )

        browser.close()

    # M15 debe ser válido para publicar
    # una nueva versión del ranking nacional.
    if (
        ranking_status.get(
            "M15"
        )
        !=
        "live"
    ):
        raise RuntimeError(
            "No se publica la actualización: "
            "M15 no ha superado la validación "
            "de categoría y líderes."
        )

    m15_validation = (
        category_validations[
            "M15"
        ]
    )

    now = (
        datetime.datetime
        .now()
        .astimezone()
    )

    # Se parte del JSON anterior para
    # conservar los rankings internos.
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
            "season": (
                SEASON_LABEL
            ),
            "filters": {
                "weapon": "Sable",
                "gender": "Femenino",
            },
            "validation": {
                "M15_rows": (
                    m15_validation[
                        "rows"
                    ]
                ),
                "M15_positive_points": (
                    m15_validation[
                        "positive_points"
                    ]
                ),
                "M15_max_points": (
                    m15_validation[
                        "maximum_points"
                    ]
                ),
                "M15_first_two": (
                    m15_validation[
                        "first_two"
                    ]
                ),
            },
            "ranking_status": (
                ranking_status
            ),
            "ranking_urls": (
                ranking_urls
            ),
            "ranking_selections": (
                ranking_selections
            ),
            "ranking_table_headers": (
                ranking_headers
            ),
            "category_validations": (
                category_validations
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
        "ACTUALIZACIÓN PUBLICABLE"
    )
    print(
        "================================"
    )

    for category in CATEGORIES:
        rows = rankings.get(
            category,
            [],
        )

        print(
            category,
            ":",
            len(rows),
            "filas · estado",
            ranking_status.get(
                category
            ),
        )

        if rows:
            print(
                "Primeras:",
                [
                    row[
                        "full_name"
                    ]
                    for row
                    in rows[:3]
                ],
            )

    print()
    print(
        "Validación M15:",
        m15_validation,
    )

    print()
    print(
        "Rankings internos preservados:",
        bool(
            output.get(
                "internal_rankings"
            )
        ),
    )

    print()
    print(
        "JSON guardado:",
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    main()

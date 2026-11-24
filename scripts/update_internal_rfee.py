#!/usr/bin/env python3

import io
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]

JSON_FILE = (
    BASE_DIR
    / "data"
    / "nacional-rfee.json"
)

CLASSIFICATION_URL = (
    "https://app.skermo.org/"
    "classification/public/RFEE"
    "?setLang=es"
)

TARGETS = {
    "M17": {
        "label": "Cadete",
        "search": (
            "RANKING INTERNO CADETE "
            "SABLE FEMENINO"
        ),
        "minimum": 7000,
    },
    "M20": {
        "label": "Junior",
        "search": (
            "RANKING INTERNO JUNIOR "
            "SABLE FEMENINO"
        ),
        "minimum": 7200,
    },
}

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "Chrome/120.0 Safari/537.36 "
            "dashboard-sable-femenino/4.0"
        ),
        "Accept-Language": (
            "es-ES,es;q=0.9,en;q=0.8"
        ),
    }
)


def clean(value):
    return " ".join(
        str(value or "").split()
    ).strip()


def normalize(value):
    return (
        clean(value)
        .casefold()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )


def parse_number(value):
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
        and "." in text
    ):
        text = (
            text
            .replace(".", "")
            .replace(",", ".")
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


def read_json():
    if not JSON_FILE.exists():
        raise FileNotFoundError(
            "No existe "
            "data/nacional-rfee.json"
        )

    return json.loads(
        JSON_FILE.read_text(
            encoding="utf-8"
        )
    )


def write_json(data):
    JSON_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        JSON_FILE
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

    # Validación antes de reemplazar
    # el JSON publicado.
    json.loads(
        temporary.read_text(
            encoding="utf-8"
        )
    )

    temporary.replace(
        JSON_FILE
    )


def wait_page(page):
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=30000,
        )

    except Exception:
        pass

    page.wait_for_timeout(
        2000
    )


def select_visible(
    page,
    requested_label,
):
    """
    Selecciona una opción por su
    texto visible.

    Evita depender de IDs internos
    de Skermo.
    """

    wanted = normalize(
        requested_label
    )

    for select in (
        page
        .locator("select")
        .all()
    ):

        options = (
            select
            .locator("option")
        )

        for index in range(
            options.count()
        ):

            option = options.nth(
                index
            )

            label = normalize(
                option.inner_text()
            )

            if label == wanted:

                select.select_option(
                    value=(
                        option
                        .get_attribute(
                            "value"
                        )
                    )
                )

                page.wait_for_timeout(
                    800
                )

                return True

    return False


def find_target_link(
    page,
    target_text,
):
    """
    Busca la fila de clasificación
    interna y devuelve:

    - nombre
    - fecha de referencia
    - enlace de descarga/apertura
    """

    target = normalize(
        target_text
    )

    for row in (
        page
        .locator("table tr")
        .all()
    ):

        row_text = clean(
            row.inner_text()
        )

        if (
            target
            not in normalize(row_text)
        ):
            continue

        date_match = re.search(
            r"\d{2}/\d{2}/\d{4}",
            row_text,
        )

        date = (
            date_match.group()
            if date_match
            else ""
        )

        links = (
            row
            .locator("a")
        )

        href = ""

        if links.count() > 0:
            for index in range(
                links.count()
            ):

                candidate = (
                    links
                    .nth(index)
                    .get_attribute("href")
                )

                if candidate:
                    href = urljoin(
                        page.url,
                        candidate,
                    )

                    # Priorizamos PDF o
                    # enlace de clasificación.
                    if (
                        ".pdf" in href.lower()
                        or
                        "classification"
                        in href.lower()
                    ):
                        break

        return {
            "name": row_text,
            "reference_date": date,
            "url": href,
        }

    return None


def html_table_rows(html):
    """
    Intenta interpretar una
    clasificación presentada
    directamente como tabla HTML.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    best_table = []

    for table in soup.select(
        "table"
    ):

        current = []

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
                    ["td", "th"]
                )
            ]

            if cells:
                current.append(cells)

        if (
            len(current)
            >
            len(best_table)
        ):
            best_table = current

    return best_table


def pdf_table_rows(
    content,
):
    """
    Extrae tablas de un PDF.

    Devuelve la tabla con mayor
    número de filas, que debería
    corresponder a la clasificación.
    """

    best_table = []

    with pdfplumber.open(
        io.BytesIO(content)
    ) as pdf:

        for page in pdf.pages:

            tables = (
                page.extract_tables()
                or
                []
            )

            for table in tables:

                cleaned = []

                for row in table:

                    if not row:
                        continue

                    cells = [
                        clean(cell)
                        for cell in row
                    ]

                    if any(cells):
                        cleaned.append(
                            cells
                        )

                if (
                    len(cleaned)
                    >
                    len(best_table)
                ):
                    best_table = cleaned

    return best_table


def find_header_row(
    table,
):
    """
    Encuentra la fila de encabezados
    usando términos habituales del
    ranking interno RFEE.
    """

    keywords = [
        "pos",
        "nombre",
        "apellidos",
        "club",
        "nacional",
        "total",
        "puntos",
    ]

    for index, row in enumerate(
        table[:15]
    ):

        combined = normalize(
            " ".join(row)
        )

        hits = sum(
            1
            for keyword
            in keywords
            if keyword
            in combined
        )

        if hits >= 2:
            return index

    return 0


def unique_headers(
    headers,
):
    """
    Evita claves duplicadas cuando
    una clasificación contiene varias
    columnas llamadas Puntos.
    """

    result = []
    used = {}

    for index, header in enumerate(
        headers
    ):

        header = (
            clean(header)
            or
            f"Columna {index + 1}"
        )

        used[header] = (
            used.get(header, 0)
            + 1
        )

        if used[header] > 1:
            header = (
                f"{header} "
                f"{used[header]}"
            )

        result.append(
            header
        )

    return result


def row_to_record(
    headers,
    row,
):
    """
    Convierte una fila en un registro
    uniforme.

    Conserva también todas las
    columnas originales para que el
    HTML pueda mostrar competiciones
    y puntos parciales.
    """

    padded = list(row)

    while len(padded) < len(
        headers
    ):
        padded.append("")

    columns = {}

    for index, header in enumerate(
        headers
    ):

        columns[header] = clean(
            padded[index]
            if index < len(padded)
            else ""
        )

    normalized_headers = {
        header: normalize(header)
        for header in headers
    }

    def value_for(
        candidates,
    ):
        for header, normalized in (
            normalized_headers.items()
        ):

            if any(
                candidate in normalized
                for candidate
                in candidates
            ):
                return columns.get(
                    header,
                    "",
                )

        return ""

    position_text = value_for(
        [
            "posicion",
            "pos.",
            "puesto",
            "ranking",
        ]
    )

    position_match = re.search(
        r"\d+",
        position_text,
    )

    position = (
        int(position_match.group())
        if position_match
        else None
    )

    name = value_for(
        [
            "nombre",
        ]
    )

    surname = value_for(
        [
            "apellido",
        ]
    )

    full_name = clean(
        f"{name} {surname}"
    )

    if not full_name:
        full_name = value_for(
            [
                "tirador",
                "deportista",
                "nombre completo",
            ]
        )

    club = value_for(
        [
            "club",
        ]
    )

    birth = value_for(
        [
            "fecha nacimiento",
            "nacimiento",
            "ano",
        ]
    )

    birth_year_match = re.search(
        r"(?:19|20)\d{2}",
        birth,
    )

    birth_year = (
        birth_year_match.group()
        if birth_year_match
        else ""
    )

    total_text = value_for(
        [
            "total",
            "puntuacion total",
            "puntos total",
        ]
    )

    # Si no existe una columna TOTAL,
    # utiliza la última columna que
    # contenga puntos/puntuación.
    if not total_text:

        point_headers = [
            header
            for header, normalized
            in normalized_headers.items()
            if (
                "punto" in normalized
                or
                "puntuacion" in normalized
            )
        ]

        if point_headers:
            total_text = columns[
                point_headers[-1]
            ]

    total = parse_number(
        total_text
    )

    return {
        "position": position,
        "name": name,
        "surname": surname,
        "full_name": full_name,
        "club": club,
        "birth_year": birth_year,
        "total": total,
        "columns": columns,
    }


def parse_classification_table(
    table,
):
    if not table:
        raise RuntimeError(
            "No se encontró ninguna tabla"
        )

    header_index = find_header_row(
        table
    )

    headers = unique_headers(
        table[header_index]
    )

    records = []

    for row in table[
        header_index + 1:
    ]:

        record = row_to_record(
            headers,
            row,
        )

        if not record["full_name"]:
            continue

        if record["position"] is None:
            continue

        records.append(
            record
        )

    if not records:
        raise RuntimeError(
            "La tabla no contiene "
            "tiradoras válidas"
        )

    return (
        headers,
        records,
    )


def download_content(
    url,
):
    response = SESSION.get(
        url,
        timeout=90,
    )

    response.raise_for_status()

    return (
        response.content,
        response.headers.get(
            "Content-Type",
            "",
        ),
    )


def classification_from_url(
    browser,
    item,
):
    url = item["url"]

    if not url:
        raise RuntimeError(
            "La fila de Skermo "
            "no contiene enlace"
        )

    content, content_type = (
        download_content(url)
    )

    is_pdf = (
        "pdf" in content_type.lower()
        or
        content.startswith(b"%PDF")
        or
        ".pdf" in url.lower()
    )

    if is_pdf:
        table = pdf_table_rows(
            content
        )

    else:
        page = browser.new_page(
            locale="es-ES",
            viewport={
                "width": 1500,
                "height": 1900,
            },
        )

        try:
            page.goto(
                url,
                wait_until=(
                    "domcontentloaded"
                ),
                timeout=120000,
            )

            wait_page(page)

            table = html_table_rows(
                page.content()
            )

        finally:
            page.close()

    headers, rows = (
        parse_classification_table(
            table
        )
    )

    return {
        "name": item["name"],
        "reference_date": (
            item["reference_date"]
        ),
        "source_url": url,
        "headers": headers,
        "rows": rows,
    }


def collect_internal_rankings(
    browser,
    previous,
):
    page = browser.new_page(
        locale="es-ES",
        viewport={
            "width": 1500,
            "height": 1900,
        },
    )

    result = {}

    try:
        page.goto(
            CLASSIFICATION_URL,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_page(page)

        # Si los filtros existen,
        # reducimos la tabla a Sable,
        # Femenino e Individual.
        select_visible(
            page,
            "Sable",
        )

        select_visible(
            page,
            "Femenino",
        )

        select_visible(
            page,
            "Individual",
        )

        wait_page(page)

        for category, config in (
            TARGETS.items()
        ):

            try:
                item = find_target_link(
                    page,
                    config["search"],
                )

                if not item:
                    raise RuntimeError(
                        "No se encontró "
                        + config["search"]
                    )

                classification = (
                    classification_from_url(
                        browser,
                        item,
                    )
                )

                classification[
                    "label"
                ] = config["label"]

                classification[
                    "category"
                ] = category

                classification[
                    "minimum"
                ] = config["minimum"]

                classification[
                    "positive_totals"
                ] = sum(
                    row["total"] > 0
                    for row
                    in classification[
                        "rows"
                    ]
                )

                if (
                    classification[
                        "positive_totals"
                    ]
                    == 0
                ):
                    raise RuntimeError(
                        "La clasificación "
                        "no contiene totales "
                        "positivos"
                    )

                result[category] = (
                    classification
                )

                print(
                    category,
                    len(
                        classification[
                            "rows"
                        ]
                    ),
                    "tiradoras;",
                    classification[
                        "positive_totals"
                    ],
                    "totales positivos",
                )

            except Exception as exc:
                print(
                    "AVISO ranking interno",
                    category,
                    exc,
                )

                if category in previous:
                    result[category] = (
                        previous[category]
                    )

                    print(
                        category,
                        "conserva la última "
                        "clasificación válida",
                    )

    finally:
        page.close()

    return result


def main():
    data = read_json()

    previous = data.get(
        "internal_rankings",
        {},
    )

    with sync_playwright() as p:

        browser = (
            p.chromium.launch(
                headless=True
            )
        )

        internal = (
            collect_internal_rankings(
                browser,
                previous,
            )
        )

        browser.close()

    if not internal:
        raise RuntimeError(
            "No se obtuvo ningún "
            "ranking interno"
        )

    data[
        "internal_rankings"
    ] = internal

    data[
        "internal_rankings_updated_at"
    ] = (
        datetime.now()
        .astimezone()
        .strftime(
            "%d/%m/%Y %H:%M %Z"
        )
    )

    data.setdefault(
        "sources",
        [],
    )

    source_exists = any(
        source.get("url")
        == CLASSIFICATION_URL
        for source
        in data["sources"]
    )

    if not source_exists:
        data["sources"].append(
            {
                "name": (
                    "Skermo RFEE · "
                    "Clasificaciones"
                ),
                "url": (
                    CLASSIFICATION_URL
                ),
                "use": (
                    "Ranking interno "
                    "Cadete y Junior "
                    "de Sable Femenino"
                ),
            }
        )

    write_json(
        data
    )

    print(
        "Ranking interno guardado en",
        JSON_FILE,
    )


if __name__ == "__main__":
    main()

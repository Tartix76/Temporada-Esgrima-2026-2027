#!/usr/bin/env python3

import datetime
import json
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "data" / "nacional-rfee.json"

RANK_URL = "https://app.skermo.org/ranking-rfee/public/RFEE?setLang=es"
CAL_URL = "https://app.skermo.org/calendar/public/RFEE?setLang=es"

SEASON = "2026-2027"
CATEGORIES = ["M13", "M15", "M17", "M20", "ABS"]


def clean(value):
    return " ".join(str(value or "").split()).strip()


def number(value):
    """Convierte 1.234,56 o 1234.56 a float."""
    text = re.sub(r"[^0-9,.\-]", "", clean(value))

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0


def read_old_data():
    """Último JSON válido, para conservar datos si una categoría falla."""
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def select_by_visible_text(page, wanted_label):
    """
    Busca wanted_label en todos los desplegables de la página.

    Así no dependemos de IDs internos de Skermo.
    """
    wanted = clean(wanted_label).casefold()

    for select in page.locator("select").all():
        options = select.locator("option")

        for i in range(options.count()):
            option = options.nth(i)
            label = clean(option.inner_text())

            if label.casefold() == wanted:
                value = option.get_attribute("value")
                select.select_option(value=value)
                page.wait_for_timeout(900)
                return True

    return False


def wait_after_filter(page):
    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=30000
        )
    except Exception:
        pass

    page.wait_for_timeout(1800)


def parse_ranking(html):
    """
    Lee la tabla que Skermo muestra después de aplicar los filtros.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for tr in soup.select("table tr"):
        cells = [
            clean(cell.get_text(" ", strip=True))
            for cell in tr.find_all(["td", "th"])
        ]

        if not cells:
            continue

        position_match = re.search(r"\d+", cells[0])

        if not position_match:
            continue

        if len(cells) < 5:
            continue

        position = int(position_match.group())

        # Formato esperado de Ranking Nacional:
        #
        # Posición
        # Nombre
        # Apellidos
        # Fecha nacimiento
        # Club
        # Puntuación

        if len(cells) >= 6:
            first_name = cells[1]
            last_name = cells[2]
            birth_date = cells[3]
            club = cells[4]
            points = number(cells[5])

        else:
            # Respaldo por si Skermo combina nombre/apellidos.
            first_name = cells[1]
            last_name = ""
            club = cells[2]
            birth_date = cells[3]
            points = number(cells[-1])

        full_name = clean(
            f"{first_name} {last_name}"
        )

        if not full_name:
            continue

        year_match = re.search(
            r"(?:19|20)\d{2}",
            birth_date
        )

        birth_year = (
            year_match.group()
            if year_match
            else ""
        )

        rows.append(
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

    # Elimina duplicados.
    unique = {}

    for row in rows:
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


def collect_one_ranking(
    browser,
    category,
):
    print()
    print(
        f"--- Actualizando {category} ---"
    )

    page = browser.new_page(
        locale="es-ES",
        viewport={
            "width": 1500,
            "height": 1900,
        },
    )

    try:
        page.goto(
            RANK_URL,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_after_filter(page)

        season_ok = select_by_visible_text(
            page,
            SEASON,
        )

        weapon_ok = select_by_visible_text(
            page,
            "Sable",
        )

        category_ok = select_by_visible_text(
            page,
            category,
        )

        gender_ok = select_by_visible_text(
            page,
            "Femenino",
        )

        missing = []

        if not season_ok:
            missing.append(SEASON)

        if not weapon_ok:
            missing.append("Sable")

        if not category_ok:
            missing.append(category)

        if not gender_ok:
            missing.append("Femenino")

        if missing:
            raise RuntimeError(
                "No se encontraron estos filtros: "
                + ", ".join(missing)
            )

        wait_after_filter(page)

        rows = parse_ranking(
            page.content()
        )

        if not rows:
            raise RuntimeError(
                "Skermo devolvió una tabla vacía"
            )

        positive = sum(
            row["points"] > 0
            for row in rows
        )

        max_points = max(
            (
                row["points"]
                for row in rows
            ),
            default=0,
        )

        print(
            f"{category}: "
            f"{len(rows)} tiradoras"
        )

        print(
            f"{category}: "
            f"{positive} con puntos > 0"
        )

        print(
            f"{category}: "
            f"máximo = {max_points}"
        )

        # Éste es el problema que queremos
        # impedir expresamente.
        if (
            category == "M15"
            and len(rows) >= 10
            and positive == 0
        ):
            raise RuntimeError(
                "M15 tiene participantes "
                "pero TODOS los puntos son 0"
            )

        return rows, page.url

    finally:
        page.close()


def collect_rankings(
    browser,
    previous,
):
    rankings = {}
    urls = {}

    for category in CATEGORIES:
        try:
            rows, url = collect_one_ranking(
                browser,
                category,
            )

            rankings[category] = rows
            urls[category] = url

        except Exception as exc:
            print(
                f"AVISO {category}: {exc}"
            )

            old_rows = previous.get(
                category,
                [],
            )

            if old_rows:
                print(
                    f"Se conservan "
                    f"{len(old_rows)} "
                    f"filas anteriores de "
                    f"{category}."
                )

            rankings[category] = old_rows
            urls[category] = RANK_URL

    return (
        rankings,
        urls,
    )


def parse_calendar(
    html,
    base_url,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    events = []

    for tr in soup.select("table tr"):
        cells = [
            clean(cell.get_text(
                " ",
                strip=True
            ))
            for cell in tr.find_all(
                ["td", "th"]
            )
        ]

        combined = " ".join(
            cells
        ).upper()

        if len(cells) < 5:
            continue

        if "SABLE" not in combined:
            continue

        if not (
            "FEMENINO" in combined
            or " FEM " in f" {combined} "
        ):
            continue

        date = next(
            (
                cell
                for cell in cells
                if re.fullmatch(
                    r"\d{2}/\d{2}/\d{4}",
                    cell,
                )
            ),
            "",
        )

        if not date:
            continue

        category = next(
            (
                category_name
                for category_name
                in CATEGORIES
                if category_name
                in combined
            ),
            "ABS",
        )

        anchor = tr.find(
            "a",
            href=True,
        )

        url = (
            urljoin(
                base_url,
                anchor["href"],
            )
            if anchor
            else base_url
        )

        events.append(
            {
                "date": date,
                "name": (
                    cells[1]
                    if len(cells) > 1
                    else "Competición RFEE"
                ),
                "category": category,
                "modality": (
                    "E"
                    if "EQUIP" in combined
                    else "I"
                ),
                "location": (
                    cells[6]
                    if len(cells) > 6
                    else ""
                ),
                "type": "Competición RFEE",
                "scope": (
                    "I"
                    if any(
                        text in combined
                        for text in [
                            "FIE",
                            "MUNDIAL",
                            "EUROPEO",
                            "GRAND PRIX",
                            "COPA DEL MUNDO",
                        ]
                    )
                    else "N"
                ),
                "registration_deadline": "",
                "links": [
                    {
                        "label": "Skermo RFEE",
                        "url": url,
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


def collect_calendar(
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

    try:
        page.goto(
            CAL_URL,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        wait_after_filter(page)

        select_by_visible_text(
            page,
            SEASON,
        )

        select_by_visible_text(
            page,
            "Sable",
        )

        select_by_visible_text(
            page,
            "Femenino",
        )

        wait_after_filter(page)

        events = parse_calendar(
            page.content(),
            page.url,
        )

        if not events:
            print(
                "AVISO: calendario vacío. "
                "Se conserva el anterior."
            )

            return (
                previous,
                page.url,
            )

        print(
            f"Calendario: "
            f"{len(events)} eventos"
        )

        return (
            events,
            page.url,
        )

    except Exception as exc:
        print(
            f"AVISO calendario: {exc}"
        )

        return (
            previous,
            CAL_URL,
        )

    finally:
        page.close()


def validate_m15(rankings):
    m15 = rankings.get(
        "M15",
        [],
    )

    rows = len(m15)

    positives = sum(
        row.get(
            "points",
            0
        ) > 0
        for row in m15
    )

    max_points = max(
        (
            row.get(
                "points",
                0
            )
            for row in m15
        ),
        default=0,
    )

    validation = {
        "M15_rows": rows,
        "M15_positive_points": positives,
        "M15_max_points": max_points,
    }

    if rows == 0:
        raise RuntimeError(
            "M15 está vacío"
        )

    if positives == 0:
        raise RuntimeError(
            "M15 no contiene "
            "ninguna puntuación positiva"
        )

    if max_points <= 0:
        raise RuntimeError(
            "M15_max_points "
            "no es válido"
        )

    return validation


def main():
    previous = read_old_data()

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

    with sync_playwright() as p:
        browser = (
            p.chromium.launch(
                headless=True
            )
        )

        rankings, ranking_urls = (
            collect_rankings(
                browser,
                previous_rankings,
            )
        )

        calendar, calendar_url = (
            collect_calendar(
                browser,
                previous_calendar,
            )
        )

        browser.close()

    # No generamos un JSON nuevo
    # si M15 sigue incorrecto.
    validation = validate_m15(
        rankings
    )

    now = (
        datetime.datetime
        .now()
        .astimezone()
    )

    output = {
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
        "season": SEASON,
        "filters": {
            "weapon": "Sable",
            "gender": "Femenino",
        },
        "validation": validation,
        "ranking_urls": ranking_urls,
        "rankings": rankings,
        "calendar_url": calendar_url,
        "calendar": calendar,

        # Por ahora mantenemos los
        # resultados detallados anteriores.
        "results": previous.get(
            "results",
            [],
        ),

        "sources": [
            {
                "name": (
                    "Skermo RFEE · "
                    "Ranking Nacional"
                ),
                "url": RANK_URL,
            },
            {
                "name": (
                    "Skermo RFEE · "
                    "Calendario"
                ),
                "url": CAL_URL,
            },
        ],
    }

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        OUT.with_suffix(
            ".json.tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Verificación final del JSON.
    json.loads(
        temporary.read_text(
            encoding="utf-8"
        )
    )

    temporary.replace(
        OUT
    )

    print()
    print(
        "Datos RFEE actualizados."
    )

    print(
        "Validación M15:",
        validation,
    )

    print(
        "Archivo:",
        OUT,
    )


if __name__ == "__main__":
    main()

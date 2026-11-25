#!/usr/bin/env python3

import json
from datetime import datetime
from pathlib import Path


# ============================================================
# RUTAS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

NATIONAL_JSON = (
    BASE_DIR
    / "data"
    / "nacional-rfee.json"
)

FALLBACK_JSON = (
    BASE_DIR
    / "data"
    / "internal-rfee-fallback.json"
)


# ============================================================
# UTILIDADES
# ============================================================

def read_json(path):
    """
    Lee un fichero JSON y devuelve
    su contenido como diccionario.
    """

    if not path.exists():
        return {}

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as error:

        print(
            f"ERROR leyendo {path}: "
            f"{error}"
        )

        return {}


def write_json(
    path,
    data,
):
    """
    Escribe el JSON primero en un
    fichero temporal.

    Solo reemplaza el fichero real
    cuando el nuevo JSON es válido.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = (
        path.with_suffix(
            ".json.tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Comprobación de seguridad.
    json.loads(
        temporary.read_text(
            encoding="utf-8"
        )
    )

    temporary.replace(
        path
    )


def count_valid_rows(
    ranking,
):
    """
    Cuenta filas del ranking interno
    que tienen nombre y total.
    """

    rows = ranking.get(
        "rows",
        [],
    )

    return sum(
        1
        for row in rows
        if (
            row.get("full_name")
            and
            float(
                row.get(
                    "total",
                    0
                )
                or
                0
            )
            >
            0
        )
    )


def validate_internal(
    internal,
):
    """
    Comprueba qué categorías contienen
    datos internos utilizables.
    """

    valid = {}

    for category in [
        "M17",
        "M20",
    ]:

        ranking = internal.get(
            category
        )

        if not ranking:
            continue

        rows = ranking.get(
            "rows",
            [],
        )

        if not rows:
            continue

        valid_rows = count_valid_rows(
            ranking
        )

        if valid_rows == 0:
            continue

        valid[category] = ranking

    return valid


# ============================================================
# DATOS FALLBACK
# ============================================================

def load_fallback():
    """
    Carga la última clasificación
    interna oficial almacenada.
    """

    print()
    print(
        "Buscando fallback de "
        "ranking interno..."
    )

    fallback = read_json(
        FALLBACK_JSON
    )

    if not fallback:

        raise RuntimeError(
            "No existe o está vacío "
            "data/internal-rfee-fallback.json"
        )

    valid = validate_internal(
        fallback
    )

    if not valid:

        raise RuntimeError(
            "internal-rfee-fallback.json "
            "no contiene rankings "
            "M17/M20 válidos"
        )

    for category, ranking in (
        valid.items()
    ):

        ranking[
            "data_status"
        ] = "fallback"

        ranking[
            "status_message"
        ] = (
            "Última clasificación "
            "interna oficial válida "
            "almacenada"
        )

        ranking[
            "loaded_at"
        ] = (
            datetime.now()
            .astimezone()
            .isoformat(
                timespec="seconds"
            )
        )

        print(
            category,
            ":",
            len(
                ranking.get(
                    "rows",
                    []
                )
            ),
            "tiradoras,",
            count_valid_rows(
                ranking
            ),
            "con puntos positivos",
        )

    return valid


# ============================================================
# RANKING EXISTENTE
# ============================================================

def get_existing_internal(
    national,
):
    """
    Si nacional-rfee.json ya contiene
    un ranking interno válido, lo
    conserva.

    Esto evita perder datos válidos
    por una actualización posterior.
    """

    internal = national.get(
        "internal_rankings",
        {},
    )

    valid = validate_internal(
        internal
    )

    if valid:

        print()
        print(
            "Ya existe ranking interno "
            "válido en nacional-rfee.json."
        )

        for category, ranking in (
            valid.items()
        ):

            print(
                category,
                ":",
                len(
                    ranking.get(
                        "rows",
                        []
                    )
                ),
                "tiradoras",
            )

    return valid


# ============================================================
# FUENTES
# ============================================================

def add_source(
    national,
):
    """
    Añade la fuente del ranking interno
    sin duplicarla.
    """

    sources = national.setdefault(
        "sources",
        [],
    )

    source_url = (
        "https://app.skermo.org/"
        "classification/public/RFEE"
        "?setLang=es"
    )

    exists = any(
        source.get("url")
        ==
        source_url
        for source in sources
    )

    if not exists:

        sources.append(
            {
                "name": (
                    "Skermo RFEE · "
                    "Clasificaciones internas"
                ),
                "url": source_url,
                "use": (
                    "Ranking interno Cadete "
                    "y Junior de "
                    "Sable Femenino"
                ),
            }
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "ACTUALIZACIÓN RANKING INTERNOO"
    )

    print(
        "================================"
    )

    print()


    # --------------------------------------------------------
    # Leer nacional-rfee.json
    # --------------------------------------------------------

    if not NATIONAL_JSON.exists():

        raise RuntimeError(
            "No existe "
            "data/nacional-rfee.json"
        )


    national = read_json(
        NATIONAL_JSON
    )


    if not national:

        raise RuntimeError(
            "nacional-rfee.json "
            "está vacío o no es válido"
        )


    # --------------------------------------------------------
    # 1. Intentar conservar datos
    # internos existentes.
    # --------------------------------------------------------

    internal = (
        get_existing_internal(
           national
        )
    )


    # --------------------------------------------------------
    # 2. Si no existen, cargar fallback.
    # --------------------------------------------------------

    if not internal:

        print()
        print(
            "No existe ranking interno "
            "válido en el JSON nacional."
        )

        print(
            "Se utilizará la última "
            "clasificación oficial "
            "almacenada."
        )

        internal = (
            load_fallback()
        )


    # --------------------------------------------------------
    # Comprobación final.
    # --------------------------------------------------------

    if not internal:

        raise RuntimeError(
            "No se obtuvo ningún "
            "ranking interno válido"
        )


    valid_categories = list(
        internal.keys()
    )


    if not valid_categories:

        raise RuntimeError(
            "No existen categorías "
            "internas válidas"
        )


    # --------------------------------------------------------
    # Guardar ranking interno
    # dentro del JSON nacional.
    # --------------------------------------------------------

    national[
        "internal_rankings"
    ] = internal


    national[
        "internal_rankings_updated_at"
    ] = (
        datetime.now()
        .astimezone()
        .strftime(
            "%d/%m/%Y %H:%M %Z"
        )
    )


    national[
        "internal_rankings_status"
    ] = (
        "fallback"
        if any(
            ranking.get(
                "data_status"
            )
            ==
            "fallback"
            for ranking
            in internal.values()
        )
        else
        "existing"
    )


    add_source(
        national
    )


    # --------------------------------------------------------
    # Escribir JSON.
    # --------------------------------------------------------

    write_json(
        NATIONAL_JSON,
        national,
    )


    # --------------------------------------------------------
    # Resumen.
    # --------------------------------------------------------

    print()
    print(
        "Ranking interno guardado."
    )

    print(
        "Categorías disponibles:",
        ", ".join(
            valid_categories
        ),
    )


    for category in (
        valid_categories
    ):

        ranking = internal[
            category
        ]

        rows = ranking.get(
            "rows",
            [],
        )

        valid_rows = (
            count_valid_rows(
                ranking
            )
        )

        print(
            category,
            ":",
            len(rows),
            "filas,",
            valid_rows,
            "con puntos positivos",
        )


    print()
    print(
        "Archivo actualizado:"
    )

    print(
        NATIONAL_JSON
    )

    print()
    print(
        "Actualización de ranking "
        "interno completada."
    )


if __name__ == "__main__":

    main()

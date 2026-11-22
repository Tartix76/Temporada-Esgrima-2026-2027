# Sable femenino 2026-27 · Nacional y Regional Madrid

## Publicar en GitHub Pages
1. Sube el contenido completo del ZIP a la raíz de un repositorio público.
2. Ve a **Settings > Pages**.
3. En **Source**, elige **Deploy from a branch**.
4. Selecciona **main** y **/(root)**.
5. Ve a **Actions > Actualizar datos FME > Run workflow** para obtener el primer snapshot regional.

## Qué hace cada archivo
- `index.html`: selector Nacional/Regional y botón para descargar la última versión publicada.
- `nacional.html`: dashboard nacional original.
- `regional.html`: dashboard regional que lee `data/regional-fme.json`.
- `scripts/update_fme.py`: recoge ranking y calendario desde Skermo y enlaces de resultados desde Engarde.
- `.github/workflows/update-dashboard.yml`: actualización manual y automática cada 6 horas.

## Importante
El botón de la web **no ejecuta GitHub Actions**. Solo fuerza la descarga del último snapshot publicado, sin caché. La extracción real se ejecuta en GitHub Actions cada 6 horas o manualmente con **Run workflow**. Esto evita publicar tokens de GitHub en el navegador.

El script usa primero HTTP directo y, si Skermo carga las tablas mediante JavaScript, utiliza Chromium con Playwright. Si una fuente falla o devuelve una tabla vacía, conserva los últimos datos válidos.

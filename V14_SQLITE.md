# v14 · Catálogo SQLite

Rama de desarrollo: `dev/catalogo-sqlite`. No fusionar con `master` hasta validar en Ubuntu.

## Qué cambia

- La lista M3U continúa leyéndose en bloques desde archivo o HTTP(S).
- Los bloques se guardan inmediatamente en `~/.local/share/iptv-video/catalog.sqlite3`.
- La búsqueda usa SQLite FTS5 (Unicode, sin tildes, coincidencia por prefijo), indexando título, grupo y metadatos.
- La tabla no materializa más de `DISPLAY_LIMIT` filas, aunque el catálogo tenga cientos de miles.
- Los grupos se obtienen mediante SQL; el total de coincidencias corresponde al resultado completo.
- La base persiste entre ejecuciones: puedes abrir la aplicación y explorar el último catálogo importado sin volver a descargarlo.
- Favoritos persistentes y exportación/importación M3U integradas.
- Reproducción local mpv/IPC y Google Cast/FFmpeg sin cambios intencionados.

## Pruebas

```bash
cd ~/Documentos/IPTV
git fetch origin
git switch dev/catalogo-sqlite
git pull --ff-only origin dev/catalogo-sqlite
source venv/bin/activate
python -m unittest discover -p 'test_*.py' -v
python app.py
```

Probar: búsqueda por nombre, búsqueda sin tilde, filtros de grupos, cambio de canal en mpv sin mover ventana, envío Cast, cancelación a mitad de importación, favoritos y reinicio de aplicación.

Comprobar la cantidad:

```bash
python - <<'PY'
from catalog_sqlite import Catalog
c=Catalog()
print('Canales:',c.count())
print('Grupos:',len(c.groups()))
c.close()
PY
```

El archivo `.sqlite3` es local y puede contener credenciales incluidas en las URL de emisión. **No subir a GitHub** esta base, archivos M3U personales, listas `get.php`, logs o entornos virtuales.

## Límites conocidos

- No incorpora aún agrupación TV/series/películas ni EPG; quedan para v15+.
- No existe paginación visible en la interfaz: se muestran las primeras 3000 coincidencias y debe afinarse la búsqueda.
- La importación mantiene un catálogo anterior persistido hasta que se elija una nueva lista; una carga nueva sustituye los canales, no los favoritos.
- FTS5 funciona por tokens/prefijos; no es búsqueda de subcadenas internas arbitrarias.
- La escritura SQLite y renderizado están en el hilo principal, aunque la lectura M3U usa un hilo de fondo. Es necesario medir fluidez real con listas de ~100 MB antes del merge.

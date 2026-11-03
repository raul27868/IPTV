# Xtream Codes: perfiles y análisis

Esta fase añade perfiles con varios servidores, almacenando URL/usuario en ~/.config/iptv-video/xtream-profiles.json y la contraseña en el llavero del escritorio (GNOME Keyring mediante Python keyring). La contraseña no se escribe en el JSON ni en el repositorio.

## Ubuntu: dependencia opcional

Instalar en el venv: `python -m pip install keyring` y asegurarse de que GNOME Keyring / Secret Service está disponible y desbloqueado. La prueba de conexión sin guardar sigue funcionando sin keyring. Si no hay almacén seguro no se permite guardar una contraseña, en lugar de crear un fichero en claro.

## Uso

1. En Xtream Codes, introducir nombre de perfil, servidor, usuario y contraseña y pulsar Guardar perfil.
2. Elegir un perfil de la lista en una sesión posterior para restaurar la conexión.
3. Pulsar Comprobar conexión o Analizar catálogo, que consulta colecciones TV, VOD y Series sin modificar SQLite.
4. Exportar informe seguro JSON para compartir resultados sin credenciales ni URLs.

## Límites actuales

- Las consultas por colección tienen límite de respuesta 6 MiB; en servidores muy grandes pueden mostrar que la consulta supera ese tamaño en lugar de analizarla.
- El análisis de colección en esta versión solo cuenta elementos y campos estructurales, no reproduce el contenido ni sincroniza el catálogo.
- Las credenciales se envían al servidor consultado; usar HTTPS cuando sea posible.
- El borrado de un perfil intenta borrar también la entrada del llavero.
- No se han fusionado todavía los cambios con master.
## Fase A: interfaz principal

La cabecera de IPTV Vídeo ahora permite seleccionar **URL M3U**, **Archivo M3U** y **Xtream Codes**. En Xtream se elige un perfil almacenado y se pulsa **Conectar** para explorar sus categorías TV, Películas y Series en la propia ventana principal. El botón **Gestionar perfiles…** permite crear o borrar conexiones; el selector principal se actualiza después de hacerlo.

Los controles de mpv y Google Cast se comparten entre las fuentes. El cambio de fuente no borra la base SQLite M3U ni detiene la reproducción. La búsqueda y los favoritos unificados quedan para la fase siguiente. El explorador Xtream lee bajo demanda los contenidos de cada categoría y hasta 3.000 filas visibles por grupo; las temporadas y episodios se consultan al abrir una serie. El selector de fuente y perfil aún no se recuerda automáticamente entre arranques (fase C).

## Explorar API (herramienta avanzada)

En la cabecera Xtream está disponible **Explorar API**. Utiliza el perfil seleccionado sin volver a escribir usuario ni contraseña. El explorador permite elegir una operación de lectura de `player_api.php`, introducir o editar sus parámetros y pulsar **Enviar GET**.

Por ejemplo: `action=get_series_info&series_id=123` (sustituye 123 por un ID real mostrado en la columna «ID / Temporada» del catálogo Xtream). También están disponibles `get_vod_info&vod_id=…`, categorías, canales, series, películas y consultas EPG compatibles.

La respuesta se visualiza como JSON formateado; la vista está limitada a los primeros 100.000 caracteres y la respuesta completa filtrada se puede copiar o exportar. Por precaución el límite por consulta es 16 MB; no pretende sustituir los análisis incrementales de catálogos masivos. Solo se aceptan acciones GET de lectura sobre `player_api.php`; no se permite modificar credenciales o rutas de API arbitrarias.

**Privacidad:** se ocultan campos y URLs privados conocidos, pero una API externa puede devolver campos no previstos. Revisa cualquier exportación antes de compartirla públicamente. No guardes capturas de URLs Xtream que incluyan contraseñas. Las credenciales siguen protegidas por el llavero de Ubuntu.

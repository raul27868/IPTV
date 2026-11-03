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

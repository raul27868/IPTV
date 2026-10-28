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
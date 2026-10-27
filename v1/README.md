# IPTV Audio — Ubuntu

Aplicación de escritorio para explorar listas M3U/M3U Plus y escuchar exclusivamente el audio de transmisiones compatibles.

## Instalación (Ubuntu / Linux Mint)

```bash
sudo apt update
sudo apt install python3 python3-tk mpv
```

No necesita `pip`, entorno virtual ni ejecutar un servidor web.

## Ejecución

```bash
python3 app.py
```

En la ventana:
1. Pega la URL completa de tu lista `get.php?username=...&password=...&type=m3u_plus&output=ts` y pulsa **Cargar URL**, o pulsa **Abrir archivo…** para importar una lista ya descargada (incluido el archivo de ejemplo `index.ts`).
2. Busca por nombre y filtra por grupo; haz clic en una fila para consultar metadatos.
3. Pulsa **Reproducir audio** o haz doble clic en la fila. Pulsa **Detener** para parar.

## Notas

- El archivo `index.ts` proporcionado es texto M3U, no un vídeo ni código TypeScript.
- `output=ts` indica habitualmente el formato del flujo individual, no necesariamente el formato de la lista descargada.
- Solo se reproduce el audio (`mpv --no-video`). La compatibilidad depende del códec, de la red y del servidor IPTV.
- El campo URL puede contener una contraseña: la aplicación no la guarda en disco, ni la escribe en registros, ni muestra la URL completa en la ficha de canal. Utiliza preferentemente conexiones HTTPS si el servicio las admite.
- El programa no elude DRM, contraseñas ni restricciones del proveedor. Utilízalo únicamente con fuentes para las que tengas autorización.
- No tiene EPG en tiempo real, grabación ni favoritos en esta primera versión.
- Las listas de gran tamaño pueden tardar un instante en representarse en la tabla.

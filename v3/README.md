# IPTV Vídeo Ubuntu — v3 (carga progresiva)

Aplicación Tkinter para cargar y examinar listas M3U por URL o archivo y reproducir vídeos con mpv. Utilizar solamente emisiones para las que se tenga autorización.

## Instalar y arrancar

```bash
sudo apt update
sudo apt install python3 python3-tk mpv
python3 app.py
```

## Cambios v3

- Las listas HTTP se reciben en bloques de 64 KiB: los canales se muestran en la tabla por lotes mientras continúa la descarga, sin esperar a recibir el fichero completo.
- Buscar, filtrar y reproducir los canales ya recibidos durante la descarga.
- Estado en tiempo real: canales detectados y megabytes recibidos.
- «Cancelar carga» detiene la incorporación de datos y conserva los canales que ya se han mostrado. Al cancelar, la conexión se cierra cuando regrese la siguiente lectura de red.
- Hasta 200 MiB como límite defensivo (si el proveedor envía una lista mucho mayor será necesario incrementar este límite).
- El vídeo se reproduce mediante mpv en una ventana independiente.
- El diagnóstico de errores está en `~/.local/state/iptv-video/iptv.log`; las URLs de solicitud no se escriben en el log.

**Nota:** algunos servidores retrasan el envío y no permiten una visualización verdaderamente inmediata; la primera entrada aparece cuando se ha recibido su línea URL completa. La codificación incremental se interpreta como UTF-8. Para listas UTF-16 o codificaciones antiguas, utiliza la carga local o adapta el detector de codificación.

## Pruebas

```bash
python3 -m unittest discover -v
```

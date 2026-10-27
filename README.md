## Cambios v11

- En Información del elemento seleccionado aparece la URL completa, con botón para copiarla. **Atención:** algunas URL incluyen usuario y contraseña.
- Cast: rutas `.ts`, `.m2ts` y enlaces de formato desconocido emplean automáticamente FFmpeg/HLS aunque esté elegido Directo. MP4 y M3U8 siguen usando Directo.
- Si falla HLS, revisar solicitudes al servidor temporal, cortafuegos y trazas FFmpeg.

# IPTV Vídeo Ubuntu — v10

## Cambios de esta versión

- Número de versión visible en la esquina inferior derecha.
- Entrada independiente **Reproducir enlace directo**: acepta URL HTTP(S) de un flujo MP4, HLS (`.m3u8`), MPEG-TS u otro formato compatible. No altera la lista M3U cargada. Utiliza el procesador elegido (mpv local o Google Cast).
- Registro de conexión/receptor Cast, tipo MIME y estado de reproducción.
- En **Compatible (FFmpeg/HLS)**, el registro muestra cuándo se abre el servidor HLS temporal y si el televisor solicita la lista o los segmentos.

**Diagnóstico:** que aparezca el icono Cast en el televisor indica que se ha iniciado el receptor, no que el contenido se pueda descargar/decodificar. Prueba primero la URL directa `https://storage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4` en modo **Directo**. Después una URL de emisión real en **Compatible (FFmpeg/HLS)**. Consulta `~/.local/state/iptv-video/iptv.log`, sin compartir credenciales.

Si la TV no solicita ningún segmento en modo compatible, revisa firewall y conectividad desde Google TV al servidor HLS temporal de Ubuntu. No abras puertos a Internet: la función está destinada a la red local.

---

# IPTV Vídeo para Ubuntu — v6

Explorador de listas M3U/M3U Plus, tanto desde URL como desde archivos locales voluminosos, con reproducción de vídeo en una ventana de `mpv`.

## Requisitos

```bash
sudo apt update
sudo apt install python3 python3-tk mpv
```

## Ejecución

```bash
python3 app.py
```

## Cambios en v4

- Los **archivos locales** se leen incrementalmente (bloques de 64 KiB), sin `read_bytes()` para el fichero completo.
- Los canales se muestran a medida que se leen y pueden reproducirse antes de finalizar la carga.
- Barra textual de progreso con MB y porcentaje para archivos locales; para URL también cuando el servidor facilita `Content-Length`.
- **Cancelar carga** preserva los canales ya incorporados.
- Se muestran como máximo **3000 coincidencias** en la tabla por motivos de rendimiento, aunque todos los canales cargados se mantienen en memoria y se incluyen en la búsqueda. Acota mediante el filtro de grupo o texto si hay más de 3000 coincidencias.
- Tamaño máximo permitido: 512 MiB. Es un límite de seguridad, no una promesa de rendimiento ilimitado: con cientos de miles de canales puede haber consumo elevado de RAM.

## Diagnóstico

El botón `Diagnóstico` muestra el registro de errores. Registro en `~/.local/state/iptv-video/iptv.log`. No compartas URLs con claves, usuarios ni contraseñas.

## Consideraciones

- En archivos locales, la primera fila aparece tras encontrar una entrada M3U completa.
- Una URL puede tardar en empezar a producir resultados si el proveedor prepara el contenido antes de enviarlo.
- Las URLs de los streams pueden contener credenciales: trata los archivos y registros como información privada.
- El archivo `index.ts` puede ser una lista M3U a pesar de su extensión; el contenido determina el formato.


## Nuevo en v5: Procesador → Google Cast

Esta versión añade un desplegable **Procesador**, similar al de VLC, con modo **Local (mpv)** y detección de **Chromecast / televisores Google Cast**.

### Instalar (Ubuntu)

`python3-tk`, `python3-venv` y `mpv` son dependencias del sistema:

```bash
sudo apt update
sudo apt install python3 python3-tk python3-venv mpv
cd iptv_audio_ubuntu
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-cast.txt
.venv/bin/python app.py
```

Si no deseas usar Google Cast, puedes seguir ejecutando `python3 app.py` sin instalar el paquete opcional.

### Uso

1. Asegura que Ubuntu y Chromecast estén en la misma red local (sin aislamiento Wi-Fi).
2. Pulsa **Buscar dispositivos**; selecciona el Chromecast encontrado en **Procesador**.
3. Selecciona un canal y pulsa **Ver vídeo**.
4. Para volver al PC, elige **Local (mpv)** y reproduce un canal.
5. **Detener** ordena detener el Cast iniciado por la aplicación.

### Límites técnicos

* Compatible **únicamente con Google Cast**, no DLNA/UPnP, AirPlay ni Miracast. No transcodifica flujos.
* El dispositivo reproduce **directamente la URL**: debe poder acceder por su cuenta al servidor y aceptar el protocolo, códecs y contenedor.
* IPTV `.ts`, servidores que dependen de cookies/cabeceras, enlaces `localhost`, URLs caducadas o certificados no admitidos pueden fallar aunque `mpv` reproduzca el canal. El tipo MIME se deduce por la extensión y puede ser incorrecto para ciertos proveedores.
* Recibir confirmación de envío de la orden **no garantiza** que el televisor esté reproduciendo. La reproducción real necesita verificación en el receptor.
* La dirección enviada al Chromecast puede contener tokens de acceso: úsalo solo en redes y dispositivos de confianza. No compartas registros ni listas privadas.

## Nuevo en v6: Google TV / Android TV — modo compatible

Esta versión ofrece dos modos, junto al selector **Procesador**:

- **Directo (menos CPU):** envía la URL al televisor. Se recomienda probar primero.
- **Compatible (FFmpeg/HLS):** el PC recibe el flujo, lo transforma a H.264/AAC (máximo 720p) y lo publica temporalmente como HLS mediante HTTP en la red local. Puede funcionar con emisiones MPEG-TS o códecs que no reproduzca el modo directo. Consume más CPU y añade latencia.

Instala también FFmpeg:

```bash
sudo apt install ffmpeg
```

En el modo compatible, el televisor debe poder llegar **por HTTP a la IP LAN de Ubuntu**. Comprueba el cortafuegos (`ufw`), el aislamiento de dispositivos del Wi-Fi y que ambos están en la misma red. La aplicación abre un puerto TCP aleatorio mientras está activa la emisión; no abras puertos del router hacia Internet. El acceso HLS utiliza un identificador aleatorio temporal: es un control básico de acceso, **no cifra el vídeo**. Utiliza una red local de confianza.

El arranque de FFmpeg puede tardar unos segundos; el PC debe permanecer encendido. El botón **Detener** libera el proceso, apaga el servidor y elimina los segmentos temporales. Esta versión no soporta DRM, autenticaciones que requieran cabeceras/cookies personalizadas, flujos UDP/RTSP para Cast, ni garantiza la reproducción de todas las emisiones. Google Cast informa de la aceptación de una orden, no de la reproducción correcta: verifícalo en el televisor.

**Pruebas sugeridas:** primero un canal en modo Directo; si hay pantalla negra, cambia a Compatible. Si no hay imagen, consulta **Diagnóstico** y prueba que Ubuntu puede reproducir la emisión con mpv. Si el televisor no alcanza el PC por red local, HLS no funcionará.

No compartas URLs de reproducción que contengan credenciales. La aplicación no almacena las URLs completas en el registro, pero el proceso FFmpeg recibe la URL y el sistema operativo podría mostrarla en herramientas de inspección de procesos.


## Diagnóstico Google TV (v7)

El programa ahora registra los cambios `UNKNOWN / BUFFERING / PLAYING / IDLE` y el
`idle_reason` del receptor durante los primeros 22 segundos. `Envío solicitado`
no confirmaba la reproducción en versiones anteriores. Revisa el botón Diagnóstico
o `~/.local/state/iptv-video/iptv.log`.

**Prueba de control:** usa una lista M3U local con una única entrada de vídeo MP4
público compatible para distinguir problemas de Google Cast de incompatibilidad
con el IPTV. No publiques URLs IPTV completas ni credenciales al compartir el log.

**Modo compatible:** el televisor debe poder abrir HTTP en el puerto temporal
del ordenador. Verifica la misma LAN, la ausencia de aislamiento Wi-Fi y el
cortafuegos UFW; el descubrimiento mDNS por sí solo no garantiza ese acceso.

## Corregido en v8: vida útil de Google Cast / Zeroconf

La v7 cerraba el navegador Zeroconf al acabar la búsqueda, pero conservaba
objetos de conexión dependientes de él. Además, intentaba reutilizar conexiones
fallidas. La v8 conserva el servicio de descubrimiento, crea un objeto de
conexión nuevo en cada intento y desconecta los anteriores. Los cierres se
realizan también al terminar la aplicación.

Diagnóstico independiente (sin IPTV):

```bash
python google_tv_probe.py
```

Se enviará un MP4 público a la TV seleccionada. Esta prueba permite aislar
los problemas de conectividad Cast de los problemas de compatibilidad IPTV.
No garantiza que todos los modelos/firmwares Google TV acepten el contenido.

### Versión 12 — mantener posición y tamaño de la ventana mpv

Al reproducir otro canal en **Local (mpv)**, la aplicación reutiliza el mismo proceso
mpv mediante un socket IPC Unix privado y el comando `loadfile <URL> replace`.
Por ello se conservan la posición, las dimensiones y el estado de ventana completa.
Si mpv se ha cerrado, se inicia una ventana nueva; si IPC falla, se reinicia
el reproductor y el problema se registra en el diagnóstico. Para cerrar la
ventana local, utiliza **Detener**. El comando funciona igualmente para un enlace
M3U o una URL directa. El socket IPC se elimina al detener el reproductor.

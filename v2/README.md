# IPTV Vídeo v2 (Ubuntu)

Explorador M3U/M3U Plus y reproductor de vídeo en directo.

## Instalación
```bash
sudo apt update
sudo apt install python3 python3-tk mpv
```
## Inicio
```bash
python3 app.py
```

Pega la URL M3U en el campo correspondiente y pulsa **Cargar URL**, o carga una lista `.m3u`, `.m3u8`, `.ts` o `.txt` local. Selecciona un canal y pulsa **Ver vídeo** o haz doble clic. El vídeo se abrirá en una ventana independiente de mpv; **Detener** termina la reproducción.

## Diagnóstico

El error de carga muestra ahora etapa, tipo, motivo, servidor y duración. El botón **Diagnóstico** abre el registro rotativo ubicado en `~/.local/state/iptv-video/iptv.log`.

No se registran las URLs completas. Revisa igualmente los registros antes de compartirlos; los nombres y servidores pueden ser información privada. Usa fuentes de emisión autorizadas.

## Límites

La ventana de vídeo es **externa**, no incrustada en la interfaz principal. No se eluden DRM ni requisitos de acceso. La lista puede indicar `output=ts`, que describe el formato de los flujos y no exige que el propio archivo de lista sea un vídeo.

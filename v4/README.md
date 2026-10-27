# IPTV Vídeo para Ubuntu — v4

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

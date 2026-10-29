"""Stream large Xtream JSON arrays without materializing their contents."""
import codecs
import json
from xtream_probe import XtreamError

MAX_ITEM_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024

def iter_json_array(response, chunk_size=65536):
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8-sig")()
    buffer = ""
    pos = 0
    total = 0
    started = False
    finished = False
    eof = False
    while True:
        if not eof:
            chunk = response.read(chunk_size)
            total += len(chunk)
            if total > MAX_TOTAL_BYTES:
                raise XtreamError("Respuesta demasiado grande (límite 512 MB).")
            if chunk:
                try:
                    buffer += utf8.decode(chunk)
                except UnicodeError:
                    raise XtreamError("Codificación JSON no válida.") from None
            else:
                eof = True
                try:
                    buffer += utf8.decode(b"", final=True)
                except UnicodeError:
                    raise XtreamError("Codificación JSON no válida.") from None
        while True:
            while pos < len(buffer) and buffer[pos].isspace():
                pos += 1
            if not started:
                if pos >= len(buffer):
                    break
                if buffer[pos] != "[":
                    raise XtreamError("La respuesta no es un array JSON.")
                pos += 1
                started = True
                continue
            if finished:
                if pos < len(buffer):
                    raise XtreamError("Datos adicionales después del JSON.")
                break
            if pos < len(buffer) and buffer[pos] == "]":
                pos += 1
                finished = True
                continue
            if pos >= len(buffer):
                break
            try:
                item, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                if eof:
                    raise XtreamError("Respuesta JSON incompleta o mal formada.") from None
                break
            pos = end
            yield item
            while pos < len(buffer) and buffer[pos].isspace():
                pos += 1
            if pos >= len(buffer):
                break
            if buffer[pos] == ",":
                pos += 1
                # A trailing comma must be rejected.
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if pos < len(buffer) and buffer[pos] == "]":
                    raise XtreamError("JSON con coma final no válida.")
                continue
            if buffer[pos] == "]":
                pos += 1
                finished = True
                continue
            raise XtreamError("Separador JSON no válido.")
        if pos:
            buffer = buffer[pos:]
            pos = 0
        if len(buffer.encode("utf-8")) > MAX_ITEM_BYTES:
            raise XtreamError("Elemento JSON individual demasiado grande.")
        if eof:
            if not finished:
                raise XtreamError("Respuesta JSON incompleta.")
            return

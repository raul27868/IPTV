"""Incremental JSON array parser with bounded memory and response sizes."""
import codecs
import json
from xtream_probe import XtreamError

MAX_ITEM_CHARS = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024

def iter_json_array(response, chunk_size=65536):
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8-sig")()
    buffer = ""
    pos = 0
    total = 0
    eof = False
    state = "start"  # start, value_or_end, value, delimiter, done
    while True:
        if not eof:
            data = response.read(chunk_size)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise XtreamError("Respuesta demasiado grande (límite 512 MB).")
            try:
                buffer += utf8.decode(data, final=not data)
            except UnicodeError:
                raise XtreamError("Codificación JSON no válida.") from None
            eof = not bool(data)
        while True:
            while pos < len(buffer) and buffer[pos].isspace():
                pos += 1
            if pos >= len(buffer):
                break
            if state == "start":
                if buffer[pos] != "[":
                    raise XtreamError("La respuesta no contiene un array JSON.")
                pos += 1
                state = "value_or_end"
            elif state == "value_or_end":
                if buffer[pos] == "]":
                    pos += 1
                    state = "done"
                else:
                    state = "value"
            elif state == "value":
                try:
                    item, end = decoder.raw_decode(buffer, pos)
                except json.JSONDecodeError:
                    if eof:
                        raise XtreamError("Elemento JSON incompleto o inválido.") from None
                    break
                pos = end
                state = "delimiter"
                yield item
            elif state == "delimiter":
                if buffer[pos] == ",":
                    pos += 1
                    state = "value"
                elif buffer[pos] == "]":
                    pos += 1
                    state = "done"
                else:
                    raise XtreamError("Separador JSON no válido.")
            else:
                raise XtreamError("Contenido extra después del array JSON.")
        if pos:
            buffer = buffer[pos:]
            pos = 0
        if len(buffer) > MAX_ITEM_CHARS:
            raise XtreamError("Elemento JSON demasiado grande.")
        if eof:
            if state != "done":
                raise XtreamError("JSON incompleto.")
            return

"""Xtream connection profiles; passwords live only in OS keyring (never JSON)."""
import json
import os
from pathlib import Path

PROFILE_PATH = Path.home() / ".config" / "iptv-video" / "xtream-profiles.json"
SERVICE = "iptv-video-xtream"

class ProfileError(Exception):
    pass

def _keyring():
    try:
        import keyring
        from keyring.errors import KeyringError
        backend = keyring.get_keyring()
        if backend.priority <= 0:
            raise ProfileError("No hay almacén seguro disponible. Instala y desbloquea GNOME Keyring.")
        return keyring
    except (ImportError, Exception) as exc:
        raise ProfileError("No se pudo acceder al almacén seguro de Ubuntu. No se guardó contraseña.") from None

def load_profiles(path=PROFILE_PATH):
    try:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            return {}
        return {name: {"server": item["server"], "username": item["username"]}
                for name, item in values.items() if isinstance(item, dict)
                and isinstance(item.get("server"), str) and isinstance(item.get("username"), str)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}

def save_profile(name, server, username, password, path=PROFILE_PATH):
    from xtream_probe import normalize_server
    name = name.strip()
    if not name or len(name) > 80 or not username or not password:
        raise ProfileError("Nombre de perfil, usuario y contraseña son obligatorios.")
    server = normalize_server(server)
    keyring = _keyring()
    try:
        keyring.set_password(SERVICE, name, password)
    except Exception:
        raise ProfileError("No se pudo guardar la clave en el almacén seguro.") from None
    profiles = load_profiles(path)
    profiles[name] = {"server": server, "username": username}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(profiles, stream, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        raise ProfileError("No se pudo guardar el perfil local.") from None

def profile_credentials(name, path=PROFILE_PATH):
    profile = load_profiles(path).get(name)
    if not profile:
        raise ProfileError("Perfil no encontrado.")
    try:
        password = _keyring().get_password(SERVICE, name)
    except Exception:
        raise ProfileError("No se puede leer la contraseña del almacén seguro.") from None
    if not password:
        raise ProfileError("La contraseña de este perfil no está disponible.")
    return profile["server"], profile["username"], password

def delete_profile(name, path=PROFILE_PATH):
    profiles = load_profiles(path)
    if name not in profiles:
        return
    try:
        _keyring().delete_password(SERVICE, name)
    except Exception:
        raise ProfileError("No se pudo borrar la credencial del almacén seguro.") from None
    del profiles[name]
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(profiles, stream, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)

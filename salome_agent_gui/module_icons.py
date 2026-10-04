import os
import xml.etree.ElementTree as ET
from pathlib import Path


def icon_for(module: str, environ=None) -> str | None:
    """file:// URL of a SALOME module's own icon, read from
    $<MODULE>_ROOT_DIR/share/salome/resources/<module>/SalomeApp.xml, else
    LightApp.xml (SHAPER declares it there), or None."""
    env = os.environ if environ is None else environ
    name = str(module).lower()
    if not name.isalnum():
        return None
    root = env.get(f"{name.upper()}_ROOT_DIR")
    if not root:
        return None
    res = Path(root) / "share" / "salome" / "resources" / name
    for xml in ("SalomeApp.xml", "LightApp.xml"):
        value = _icon_param(res / xml)
        if value:
            icon = res / value
            return icon.as_uri() if icon.is_file() else None
    return None


def _icon_param(path: Path) -> str | None:
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError):
        return None
    for param in tree.iter("parameter"):
        if param.get("name") == "icon" and param.get("value"):
            return param.get("value")
    return None

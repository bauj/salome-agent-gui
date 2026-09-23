import os
import xml.etree.ElementTree as ET
from pathlib import Path


def icon_for(module: str, environ=None) -> str | None:
    """file:// URL of a SALOME module's own icon, read from
    $<MODULE>_ROOT_DIR/share/salome/resources/<module>/SalomeApp.xml, or None."""
    env = os.environ if environ is None else environ
    name = str(module).lower()
    if not name.isalnum():
        return None
    root = env.get(f"{name.upper()}_ROOT_DIR")
    if not root:
        return None
    res = Path(root) / "share" / "salome" / "resources" / name
    try:
        tree = ET.parse(res / "SalomeApp.xml")
    except (OSError, ET.ParseError):
        return None
    for param in tree.iter("parameter"):
        value = param.get("value")
        if param.get("name") == "icon" and value:
            icon = res / value
            return icon.as_uri() if icon.is_file() else None
    return None

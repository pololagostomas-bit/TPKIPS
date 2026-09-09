"""Compatibilidad: permite conservar `py .\\app.py` desde la raíz del piloto."""
import sys
from backend import app as _application

sys.modules[__name__] = _application

if __name__ == "__main__":
    _application.main()

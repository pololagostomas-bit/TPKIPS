"""Fresh, empty operational dataset for direct BL entry UI tests."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = Path(tempfile.mkdtemp(prefix="wms-direct-entry-qa-"))
os.environ["TRITON_AUTH_MODE"] = "demo"
os.environ["TRITON_DB_PATH"] = str(scratch / "qa.sqlite")
from backend import app
from backend.services import identity
from backend.wsgi import serve

app.DB_PATH = scratch / "qa.sqlite"
app.init_db()
with app.db() as connection:
    for username, role in (("qa.assistant", "ASISTENTE_RECEPCION"),
                           ("qa.auxiliary", "AUXILIAR_RECEPCION")):
        identity.save(connection, {"username": username, "display_name": username,
                                   "role": role}, "qa.fixture", app.ROLES)
port = int(sys.argv[1])
print(f"QA ONLY: http://127.0.0.1:{port}/reception", flush=True)
serve("127.0.0.1", port)

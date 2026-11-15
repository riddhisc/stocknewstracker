"""Point history at a temp database before the app is imported."""

import os
import tempfile

_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db.close()
_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
_json.close()
os.environ["HISTORY_DB"] = _db.name
os.environ["HISTORY_FILE"] = _json.name
os.environ["ENABLE_SUMMARY"] = "false"
os.environ.setdefault("FLASK_DEBUG", "0")

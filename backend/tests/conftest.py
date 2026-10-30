import os
import tempfile
from pathlib import Path

# Configuration de test AVANT l'import de l'application (base SQLite temporaire, pas de planificateur).
_tmp = tempfile.mkdtemp(prefix="sam-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["ADMIN_API_TOKEN"] = "jeton-admin-test"
os.environ["CRON_SECRET"] = "secret-cron-test"
os.environ["API_FOOTBALL_KEY"] = ""
os.environ["FOOTBALL_DATA_ORG_KEY"] = ""

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def e0_csv() -> str:
    return (FIXTURES / "E0_2526.csv").read_text(encoding="utf-8")

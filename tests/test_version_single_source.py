import subprocess
import sys

import housing_enhanced
import ingestion
import llm_interface
import slr_gui
import WebApp.app as webapp
from version import VERSION, VERSION_TAG


def test_runtime_modules_share_central_version():
    assert housing_enhanced.__version__ == VERSION
    assert llm_interface.__version__ == VERSION
    assert ingestion.__version__ == VERSION
    assert slr_gui.__version__ == VERSION


def test_webapp_template_renders_central_version():
    webapp.app.config.update(TESTING=True)
    client = webapp.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert VERSION_TAG.encode("utf-8") in response.data
    assert b"{{ version_tag }}" not in response.data


def test_static_version_strings_are_synced():
    result = subprocess.run(
        [sys.executable, "scripts/sync_version.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

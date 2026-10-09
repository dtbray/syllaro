"""Generate contracts without reading personal configs or starting workers."""

import json
from pathlib import Path

from syllaro.dashboard.api import create_app

Path("openapi.json").write_text(
    json.dumps(create_app({"main": Path("/unused")}).openapi(), indent=2) + "\n"
)

"""Keep the suite hermetic: no test may call a live provider or download weights.

Set before `ogr` is imported, so config's load_dotenv() — which never
overrides an existing variable — cannot pull a developer's real keys from
.env. Embedding then uses the local tier from cache, or the hash fallback.
"""

import os

os.environ["HF_HUB_OFFLINE"] = "1"
for _key in (
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "NVIDIA_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
):
    os.environ[_key] = ""


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_out_dir(monkeypatch, tmp_path):
    """The API writes runtime state (trial history, dataset registry, batch
    runs) under OUT_DIR; tests get their own so a developer's out/ is never
    written by the suite. Tests that need a specific OUT_DIR still set it."""
    import ogr.api.main as api_main

    monkeypatch.setattr(api_main, "OUT_DIR", tmp_path / "out")

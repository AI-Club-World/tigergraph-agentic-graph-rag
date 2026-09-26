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

# Kaggle embedding / LLM host (Round 1 helper)

`embedding_server_2.ipynb` (and the single-file variant `kaggle_server.py`) host the catalog
embedding models and an Ollama chat model on a Kaggle GPU behind a tunnel, for the Round-1
web application. **Round 2 does not use it:** `build.sh` and `run.sh` need only TigerGraph,
the corpus and an LLM endpoint. Setup steps are in the Round-1 section of the top-level README
history (`docs/round-1/`); secrets (`HF_TOKEN`, `NGROK_AUTHTOKEN`) are read from Kaggle Secrets, never from the file.

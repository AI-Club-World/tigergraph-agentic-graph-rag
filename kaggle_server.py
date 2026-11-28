# =============================================================================
#  Kaggle: 5 embedding models (GPU 0) + an Ollama chat model behind a Cloudflare tunnel
#  ONE FILE. Delete everything in the Kaggle editor, paste this, edit CONFIG.
# =============================================================================
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request

# ================================ CONFIG =====================================
# Each secret below can be given in ONE of three ways (checked in this order):
#   1) typed right here between the quotes   (simple, but anyone who can see
#      this notebook can read it -- keep the notebook PRIVATE if you do this)
#   2) a Kaggle Secret with the SAME NAME    (recommended; Add-ons > Secrets)
#   3) an environment variable of that name  (only useful outside Kaggle)

MODE = "serve"                    # "serve" = run the API
                                  # "seed"  = only download models into a reusable cache, then stop

HF_TOKEN = ""                     # Hugging Face READ token (EmbeddingGemma is gated)
API_KEY = ""                      # optional: if set, every endpoint except /health
                                  # needs the header  X-API-Key: <this value>
                                  # (or "Authorization: Bearer <value>" on /v1)

# Tunnel. Leave both empty for a Cloudflare Quick Tunnel (free, no account,
# but a NEW random *.trycloudflare.com URL on every run). For a FIXED URL,
# create a Cloudflare named tunnel (Zero Trust > Networks > Tunnels) whose
# public hostname points to http://localhost:8000, and give its token and
# hostname here (or as Kaggle Secrets of the same names).
CLOUDFLARE_TUNNEL_TOKEN = ""
CLOUDFLARE_TUNNEL_HOSTNAME = ""   # e.g. llm.example.com (no "https://")

MAX_RUNTIME_HOURS = 8             # the script stops itself after this long
CHAT_MODEL = "gemma4:12b"         # any Ollama library tag; the Round-2 agent needs one
                                  # that Ollama marks as supporting TOOLS (tool calling)
CHAT_CONTEXT = 32768              # Ollama context window (tokens). Its default is small
                                  # and silently truncates long agent prompts.
# =============================================================================

MODEL_REGISTRY = {
    "qwen3-embedding-0.6b": {
        "repo": "Qwen/Qwen3-Embedding-0.6B",
        "query_prefix": "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: ",
        "passage_prefix": "",
        "trust_remote_code": False,
    },
    "embeddinggemma-300m": {
        "repo": "google/embeddinggemma-300m",
        "query_prefix": "task: search result | query: ",
        "passage_prefix": "title: none | text: ",
        "trust_remote_code": False,
    },
    "gte-large-en-v1.5": {
        "repo": "Alibaba-NLP/gte-large-en-v1.5",
        "query_prefix": "",
        "passage_prefix": "",
        "trust_remote_code": True,   # also fetches a small code repo from HF at load time
    },
    "mxbai-embed-large-v1": {
        "repo": "mixedbread-ai/mxbai-embed-large-v1",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "passage_prefix": "",
        "trust_remote_code": False,
    },
    "bge-large-en-v1.5": {
        "repo": "BAAI/bge-large-en-v1.5",
        "query_prefix": "Represent this sentence for searching relevant passages: ",
        "passage_prefix": "",
        "trust_remote_code": False,
    },
}


def log(msg=""):
    print(msg, flush=True)


def banner(msg):
    log("=" * 64)
    log(msg)
    log("=" * 64)


if MODE not in ("serve", "seed"):
    raise ValueError(f'MODE must be "serve" or "seed", got {MODE!r}')

# ------------------------------------------------------------ dependencies
def install_dependencies():
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-U",
         "sentence-transformers>=3.4.0", "transformers>=4.51.0", "huggingface_hub",
         "fastapi", "uvicorn[standard]", "einops", "ollama", "requests", "httpx"],
        check=True,
    )
    log("dependencies installed")


install_dependencies()

# ------------------------------------------------------------ settings
def get_setting(name, hardcoded=""):
    """hardcoded value -> Kaggle Secret -> environment variable -> ''."""
    if hardcoded and hardcoded.strip():
        return hardcoded.strip()
    try:
        from kaggle_secrets import UserSecretsClient
        value = UserSecretsClient().get_secret(name)
        if value and value.strip():
            return value.strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


# ------------------------------------------------------------ cache dirs
def find_cache(name, root="/kaggle/input", max_depth=3):
    """Look for a folder called `name` inside any attached dataset/notebook output."""
    for cur, dirs, _ in os.walk(root):
        if name in dirs:
            return os.path.join(cur, name)
        if cur[len(root):].count(os.sep) >= max_depth:
            dirs[:] = []
    return None


def setup_cache_dirs():
    if MODE == "seed":
        hf_dir, ollama_dir = "/kaggle/working/hf_cache", "/kaggle/working/ollama_models"
    else:
        hf_dir, ollama_dir = "/tmp/hf_cache", "/tmp/ollama_models"
        for cache_name, dest in (("hf_cache", hf_dir), ("ollama_models", ollama_dir)):
            found = find_cache(cache_name)
            if found:
                log(f"cache found: copying {found} -> {dest}")
                shutil.copytree(found, dest, dirs_exist_ok=True)
            else:
                log(f"no '{cache_name}' attached under /kaggle/input -> will download fresh")
    os.makedirs(hf_dir, exist_ok=True)
    os.makedirs(ollama_dir, exist_ok=True)
    os.environ["HF_HOME"] = hf_dir          # must be set before huggingface_hub is imported
    os.environ["OLLAMA_MODELS"] = ollama_dir
    return hf_dir, ollama_dir


HF_DIR, OLLAMA_DIR = setup_cache_dirs()

from huggingface_hub import login, snapshot_download, list_repo_files  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException, Request   # noqa: E402
from fastapi.responses import Response                                  # noqa: E402
from pydantic import BaseModel                                          # noqa: E402

HF_TOKEN_VALUE = get_setting("HF_TOKEN", HF_TOKEN)
API_KEY_VALUE = get_setting("API_KEY", API_KEY)
if HF_TOKEN_VALUE:
    login(token=HF_TOKEN_VALUE)
    log("Hugging Face: authenticated")
else:
    log("WARNING: no HF_TOKEN found -- EmbeddingGemma (gated) will fail to download")


def local_model_dir(name):
    return os.path.join(HF_DIR, name)


def download_embedding_model(name, cfg):
    """Plain-directory download (no symlinks) so it survives being saved as
    Kaggle output and copied back later."""
    target = local_model_dir(name)
    if os.path.exists(os.path.join(target, "config.json")):
        log(f"  {name}: already present")
        return
    ignore = ["*.onnx", "*.onnx_data", "onnx/*", "openvino/*", "*.h5", "*.msgpack",
              "tf_model*", "flax_model*", "rust_model*", "*.ot", "*.gguf"]
    files = list_repo_files(cfg["repo"], token=HF_TOKEN_VALUE or None)
    if any(f.endswith(".safetensors") for f in files):
        ignore += ["*.bin", "pytorch_model*"]
    log(f"  downloading {cfg['repo']} ...")
    snapshot_download(cfg["repo"], local_dir=target, token=HF_TOKEN_VALUE or None,
                      ignore_patterns=ignore)


def dir_size_gb(path):
    total = 0
    for cur, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(cur, f))
    return total / 1e9


# ------------------------------------------------------------ Ollama
def start_ollama():
    log("installing Ollama ...")
    # recent Ollama installers need zstd; best-effort, harmless if already there
    subprocess.run("which zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)",
                   shell=True)
    subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True)
    log(f"starting Ollama server (models dir: {OLLAMA_DIR}, context {CHAT_CONTEXT}) ...")
    env = os.environ.copy()
    env["OLLAMA_CONTEXT_LENGTH"] = str(CHAT_CONTEXT)  # default is small and truncates silently
    env["OLLAMA_KEEP_ALIVE"] = "-1"                   # never unload the model between questions
    env["OLLAMA_NUM_PARALLEL"] = "1"                  # one request at a time: whole context each
    proc = subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=env)
    import ollama
    client = ollama.Client(host="http://127.0.0.1:11434")
    for _ in range(60):
        try:
            client.list()
            return proc, client
        except Exception:
            time.sleep(1)
    raise RuntimeError("Ollama server did not come up in time")


def _field(obj, key):
    return obj.get(key) if hasattr(obj, "get") else getattr(obj, key, None)


def pull_model(client, model):
    log(f"pulling {model} (instant if the cache already has it) ...")
    last = 0.0
    for p in client.pull(model, stream=True):
        total, done = _field(p, "total"), _field(p, "completed")
        if total and done and time.time() - last > 15:
            log(f"  {_field(p, 'status')}: {done / 1e9:.1f} / {total / 1e9:.1f} GB")
            last = time.time()
    log("pull complete")


def test_chat(client):
    """A short generation. Enough tokens that a model that reasons first still
    answers, and thinking off where the Ollama client supports it."""
    msgs = [{"role": "user", "content": "Reply with just the word: ready"}]
    try:
        r = client.chat(model=CHAT_MODEL, messages=msgs, options={"num_predict": 64}, think=False)
    except TypeError:  # older ollama client without `think`
        r = client.chat(model=CHAT_MODEL, messages=msgs, options={"num_predict": 64})
    return r["message"]["content"]


def tools_supported(model):
    """Whether Ollama lists the model as tool-capable (the agent needs it)."""
    try:
        import requests
        info = requests.post("http://127.0.0.1:11434/api/show", json={"model": model}, timeout=30).json()
        return "tools" in (info.get("capabilities") or [])
    except Exception:
        return None


# ------------------------------------------------------------ API
class EmbedRequest(BaseModel):
    model: str
    texts: list[str]
    prefix: str = "none"   # "query" | "passage" | "none"
    normalize: bool = True


class ChatRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 1024


def require_key(x_api_key: str = Header(default=""), authorization: str = Header(default="")):
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    if API_KEY_VALUE and API_KEY_VALUE not in (x_api_key, bearer):
        raise HTTPException(401, "missing or invalid X-API-Key / Authorization header")


LOADED = {}            # filled by run_serve()
ollama_client = None   # set by run_serve()
app = FastAPI(title="Kaggle Embedding + Chat Server")
AUTH = [Depends(require_key)]


@app.get("/health")
def health():
    try:
        pulled = CHAT_MODEL in [m["model"] for m in ollama_client.list().get("models", [])]
    except Exception:
        pulled = False
    return {"status": "ok", "embedding_models_loaded": list(LOADED.keys()),
            "chat_model_pulled": pulled}


@app.get("/embed/status", dependencies=AUTH)
def embed_status():
    results = {}
    for name, info in LOADED.items():
        try:
            t0 = time.time()
            vec = info["model"].encode(["status check"], convert_to_numpy=True)
            results[name] = {"up": True, "dim": len(vec[0]),
                             "latency_ms": round((time.time() - t0) * 1000, 1)}
        except Exception as e:
            results[name] = {"up": False, "error": str(e)}
    return {"all_up": all(r["up"] for r in results.values()), "models": results}


@app.get("/chat/status", dependencies=AUTH)
def chat_status():
    try:
        t0 = time.time()
        reply = test_chat(ollama_client)
        return {"up": True, "model": CHAT_MODEL, "tools": tools_supported(CHAT_MODEL),
                "context": CHAT_CONTEXT, "latency_ms": round((time.time() - t0) * 1000, 1),
                "sample_reply": reply}
    except Exception as e:
        return {"up": False, "model": CHAT_MODEL, "error": str(e)}


@app.get("/models", dependencies=AUTH)
def list_models():
    return {n: {"repo": i["repo"], "dim": i["dim"], "max_seq_length": i["max_seq_length"],
                "device": i["device"],
                "supports_prefix": bool(i["query_prefix"] or i["passage_prefix"])}
            for n, i in LOADED.items()}


@app.post("/embed", dependencies=AUTH)
def embed(req: EmbedRequest):
    if req.model not in LOADED:
        raise HTTPException(404, f"unknown model '{req.model}'. Available: {list(LOADED.keys())}")
    if not req.texts:
        raise HTTPException(400, "texts must be a non-empty list")
    info = LOADED[req.model]
    prefix = {"query": info["query_prefix"], "passage": info["passage_prefix"]}.get(req.prefix, "")
    vectors = info["model"].encode([prefix + t for t in req.texts],
                                   normalize_embeddings=req.normalize, convert_to_numpy=True)
    return {"model": req.model, "dim": info["dim"], "embeddings": vectors.tolist()}


@app.post("/chat", dependencies=AUTH)
def chat(req: ChatRequest):
    try:
        r = ollama_client.chat(model=CHAT_MODEL, messages=req.messages,
                               options={"temperature": req.temperature,
                                        "num_predict": req.max_tokens})
    except Exception as e:
        raise HTTPException(500, f"chat inference error: {e}")
    return {"model": CHAT_MODEL, "content": r["message"]["content"],
            "usage": {"prompt_tokens": r.get("prompt_eval_count"),
                      "completion_tokens": r.get("eval_count")}}


# OpenAI-compatible API: /v1/* is forwarded to Ollama's own OpenAI endpoint
# (chat completions with tool calling and token usage, /v1/models). Clients
# such as the Round-2 agent use LLM_BASE_URL=<public url>/v1, any API key.
@app.api_route("/v1/{path:path}", methods=["GET", "POST"], dependencies=AUTH)
async def openai_compat(path: str, request: Request):
    import httpx
    body = await request.body()
    async with httpx.AsyncClient(timeout=900) as client:
        upstream = await client.request(
            request.method, f"http://127.0.0.1:11434/v1/{path}", content=body,
            headers={"Content-Type": request.headers.get("content-type", "application/json")},
        )
    return Response(content=upstream.content, status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type"))


# ------------------------------------------------------------ tunnel
def find_free_port(start=8000, tries=10):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {start}-{start + tries}")


def cloudflared_bin():
    cf_bin = "/kaggle/working/cloudflared"
    if not os.path.exists(cf_bin):
        urllib.request.urlretrieve(
            "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
            cf_bin)
        os.chmod(cf_bin, os.stat(cf_bin).st_mode | stat.S_IEXEC)
    return cf_bin


def run_named_tunnel(token, hostname):
    """A Cloudflare named tunnel: the same https://<hostname> on every run.
    Its public hostname must point to http://localhost:8000 (the port below)."""
    proc = subprocess.Popen([cloudflared_bin(), "tunnel", "--no-autoupdate", "run", "--token", token],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        if "Registered tunnel connection" in line:
            return proc, "https://" + hostname.replace("https://", "").strip("/")
    raise RuntimeError("named tunnel exited before registering a connection")


def run_cloudflare(port):
    cf_bin = cloudflared_bin()
    proc = subprocess.Popen([cf_bin, "tunnel", "--url", f"http://localhost:{port}"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    for line in proc.stdout:
        m = pattern.search(line)
        if m:
            return proc, m.group(0)
    raise RuntimeError("cloudflared exited without printing a URL")


# ------------------------------------------------------------ MODE: seed
def run_seed():
    banner("SEED MODE: downloading models once so later runs can skip the download")
    for name, cfg in MODEL_REGISTRY.items():
        download_embedding_model(name, cfg)
    proc, client = start_ollama()
    pull_model(client, CHAT_MODEL)
    proc.terminate()
    banner("SEED COMPLETE")
    log(f"hf_cache      : {dir_size_gb(HF_DIR):.1f} GB   ({HF_DIR})")
    log(f"ollama_models : {dir_size_gb(OLLAMA_DIR):.1f} GB   ({OLLAMA_DIR})")
    log("Kaggle output is capped at 20 GB in total.")
    log("NEXT: 1) Save Version > Save & Run All (this saves the folders above as output)")
    log("      2) on that version's Output tab choose New Dataset")
    log("      3) attach the dataset to this notebook (Add Input), set MODE = 'serve', run")


# ------------------------------------------------------------ MODE: serve
def run_serve():
    global ollama_client
    import torch
    import uvicorn
    from sentence_transformers import SentenceTransformer

    tunnel_token = get_setting("CLOUDFLARE_TUNNEL_TOKEN", CLOUDFLARE_TUNNEL_TOKEN)
    tunnel_host = get_setting("CLOUDFLARE_TUNNEL_HOSTNAME", CLOUDFLARE_TUNNEL_HOSTNAME)

    banner("LOADING EMBEDDING MODELS ONTO GPU 0")
    n_gpus = torch.cuda.device_count()
    device = "cuda:0" if n_gpus > 0 else "cpu"
    log(f"visible GPUs: {n_gpus} -> embeddings on {device}")
    for name, cfg in MODEL_REGISTRY.items():
        local = local_model_dir(name)
        use_local = os.path.exists(os.path.join(local, "config.json"))
        log(f"loading {name} from {'cache' if use_local else 'Hugging Face (downloading)'} ...")
        model = SentenceTransformer(local if use_local else cfg["repo"], device=device,
                                    trust_remote_code=cfg["trust_remote_code"],
                                    token=HF_TOKEN_VALUE or None)
        LOADED[name] = {
            "model": model, "device": device,
            "dim": model.get_sentence_embedding_dimension(),
            "max_seq_length": model.max_seq_length, "repo": cfg["repo"],
            "query_prefix": cfg["query_prefix"], "passage_prefix": cfg["passage_prefix"],
        }
        log(f"  -> ready, dim={LOADED[name]['dim']}")

    banner("STARTING OLLAMA + CHAT MODEL")
    ollama_proc, ollama_client = start_ollama()
    pull_model(ollama_client, CHAT_MODEL)
    log(f"chat model ready: {CHAT_MODEL} (test reply: {test_chat(ollama_client)!r})")
    tools = tools_supported(CHAT_MODEL)
    if tools is False:
        log(f"WARNING: Ollama does not list TOOLS for {CHAT_MODEL}: the Round-2 agent needs tool "
            "calling. Pick a tool-capable model (ollama.com/search?c=tools) in CHAT_MODEL.")
    else:
        log(f"tool calling: {'supported' if tools else 'unknown'}")

    # 8000 when free: a named tunnel's hostname is configured to point there.
    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(3)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            health_ok = r.status == 200
    except Exception:
        health_ok = False
    log(f"local API {'up' if health_ok else 'FAILED its health check'} on port {port}")

    cf_proc = None
    if tunnel_token and tunnel_host:
        if port != 8000:
            log(f"WARNING: serving on port {port}, but a named tunnel usually points to 8000")
        try:
            cf_proc, public_url = run_named_tunnel(tunnel_token, tunnel_host)
            mode_label = "cloudflare named tunnel (FIXED URL)"
        except Exception as e:
            log(f"named tunnel failed: {e} -- falling back to a Quick Tunnel")
    if cf_proc is None:
        cf_proc, public_url = run_cloudflare(port)
        mode_label = "cloudflare quick tunnel (RANDOM URL -- changes every run)"

    banner("EXECUTION COMPLETE -- SERVER IS LIVE AND READY" if health_ok
           else "TUNNEL UP BUT LOCAL HEALTH CHECK FAILED -- see log above")
    log(f"Tunnel      : {mode_label}")
    log(f"Public URL  : {public_url}")
    log(f"Embeddings  : {list(LOADED.keys())}  (GPU 0)")
    log(f"Chat model  : {CHAT_MODEL}  (Ollama, context {CHAT_CONTEXT}, tools: {tools})")
    log(f"API key     : {'REQUIRED (header X-API-Key)' if API_KEY_VALUE else 'not set (endpoints are open)'}")
    log("-" * 64)
    log(f"GET  {public_url}/health          fast check, no inference")
    log(f"GET  {public_url}/embed/status    runs a real test embed")
    log(f"GET  {public_url}/chat/status     runs a real test generation")
    log(f"GET  {public_url}/models")
    log(f"POST {public_url}/embed   " + '{"model": "bge-large-en-v1.5", "texts": ["hello world"]}')
    log(f"POST {public_url}/chat    " + '{"messages": [{"role": "user", "content": "hi"}]}')
    log(f"OpenAI-compatible (Round-2 agent): LLM_BASE_URL={public_url}/v1  LLM_MODEL={CHAT_MODEL}")
    log(f"Embeddings (web UI)            : EMBEDDING_HOST_URL={public_url}")
    log("=" * 64)

    start = time.time()
    try:
        while time.time() - start < MAX_RUNTIME_HOURS * 3600:
            time.sleep(30)
            if cf_proc is not None and cf_proc.poll() is not None:
                log("cloudflare tunnel died, stopping")
                break
    finally:
        for p in (cf_proc, ollama_proc):
            if p is not None:
                p.terminate()
        banner(f"SESSION STOPPED after {(time.time() - start) / 60:.1f} min -- API no longer reachable")


if __name__ == "__main__":
    run_seed() if MODE == "seed" else run_serve()

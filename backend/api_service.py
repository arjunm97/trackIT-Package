# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from notebook_summerizer import ns
from ollama_summerizer import local_ollama
from pathlib import Path
import os, time, subprocess
from fastapi import HTTPException
from pydantic import BaseModel

app = FastAPI(title="trackIt API")

DOCKER_APP = Path("/app")
if DOCKER_APP.exists():
    # In container: repo root is /app and trackit lives at /app/trackit3.py (adjust if needed)
    REPO_ROOT = DOCKER_APP
    BACKEND_DIR = REPO_ROOT  # if trackit3.py is at /app
else:
    # On Windows/local: derive from this file's location
    BACKEND_DIR = Path(__file__).resolve().parent        # ...\trackIT-package\backend
    REPO_ROOT = BACKEND_DIR.parent 



TRACKIT_SCRIPT = BACKEND_DIR / "trackit3.py"
NOTEBOOKS_DIR = BACKEND_DIR / "notebooks"               
LOGS_DIR = BACKEND_DIR / "notebooklogs/notebook_experiments"                 
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_SYS_DIR = BACKEND_DIR / "notebooklogs/notebook_logs"
SUM_LOGS_DIR = "notebooklogs/notebook_experiments" 
RUN_STATE = {"proc": None, "notebook": None, "started_at": None, "log_file": None}

class TrackitRunRequest(BaseModel):
    notebook: str
    json: bool = False
    debounce: float = 0.5

def _is_running():
    p = RUN_STATE["proc"]
    return bool(p and (p.poll() is None))

def _ensure_notebook(name: str):
    
    nb = Path(NOTEBOOKS_DIR / name).resolve()
    if NOTEBOOKS_DIR.resolve() not in nb.parents or nb.suffix.lower() != ".ipynb":
        raise HTTPException(400, "Invalid notebook path or extension.")
    if not nb.exists():
        raise HTTPException(404, f"Notebook not found: {name}")
    return nb

class FileRequest(BaseModel):
    filename: str
    provider: str 

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/summary")
def get_summary(request: FileRequest):
    try:
        print(request)
        filename = request.filename
        provider = request.provider
        
        if provider == "bedrock":
            print('Running AWS Model')
            try:
                notebook_filename = SUM_LOGS_DIR + "/" + filename
                note_summary_object = ns(notebook_filename)
                summary = note_summary_object.driver()
                return summary
            except: 
                return "Ran into some issues runing inference on AWS Bedrock. Please check evironment variables or Try local Ollama Option"
        elif provider == "local":
            print('Running local model')
            try:
                notebook_filename = SUM_LOGS_DIR + "/" + filename
                note_summary_object = local_ollama(notebook_filename)
                summary = note_summary_object.driver()
                return summary

            except:
                return "Ran into some issues runing inference on local models."
            

    except Exception as e:
        return str(e)

## Getting logs
@app.get("/getLogs")
def get_log_files():
    filenames = os.listdir("notebooklogs/notebook_experiments")
    
    return filenames

# Getting list of notebooks
@app.get("/getNotebooks")
def get_notebooks():
    folder = "notebooks"
    try:
        
        # list only files ending with .ipynb (case insensitive)
        notebooks = [
            f for f in os.listdir(folder)
            if f.lower().endswith(".ipynb")
        ]
        print("Found notebooks:", notebooks)
        return notebooks
        
    except FileNotFoundError:
        return {"error": f"Folder '{folder}' not found"}

### Tracking Endpoints 
@app.get("/trackit/status")
def trackit_status():
    return {
        "running": _is_running(),
        "pid": RUN_STATE["proc"].pid if _is_running() else None,
        "notebook": RUN_STATE["notebook"],
        "started_at": RUN_STATE["started_at"],
        "log_file": RUN_STATE["log_file"],
    }

@app.post("/trackit/run")
def trackit_run(req: TrackitRunRequest):
    if _is_running():
        raise HTTPException(409, "trackit3 is already running")
   

    nb_path = _ensure_notebook(req.notebook)
    ts = int(time.time())
    # this is the OUTPUT that your script writes (the parsed log the summarizer reads)
    parsed_output = LOGS_DIR / f"{nb_path.stem}_io.log"
    # optional: also capture process stdout to its own file
    proc_stdout = LOGS_SYS_DIR / f"trackit3_run_{ts}.log"

    print()

    cmd = [
        "python", "-u", str(TRACKIT_SCRIPT),
        "--notebook", str(nb_path),
        "--output", str(parsed_output),
    ]
    if req.json: cmd.append("--json")
    if req.debounce != 0.5:
        cmd.extend(["--debounce", str(req.debounce)])

    f = open(proc_stdout, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            stdout=f,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
        )
    except Exception as e:
        f.close()
        print(e)
        raise HTTPException(500, f"Failed to start trackit3: {e}")

    RUN_STATE.update({
        "proc": proc,
        "notebook": nb_path.name,
        "started_at": time.time(),
        "log_file": str(parsed_output),
    })

    # You may also want to add this parsed_output filename into your /getLogs list (if that route lists *.log in LOGS_DIR)
    return {"ok": True, "pid": proc.pid, "notebook": nb_path.name, "output_file": str(parsed_output), "proc_log": str(proc_stdout), "cmd": cmd}

@app.post("/trackit/stop")
def trackit_stop():
    if not _is_running():
        return {"ok": True, "message": "trackit3 is not running"}
    try:
        p: subprocess.Popen = RUN_STATE["proc"]
        p.terminate()                 # sends SIGTERM → trackit3 exits cleanly
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        RUN_STATE.update({"proc": None, "notebook": None, "started_at": None})
        return {"ok": True, "message": "trackit3 stopped"}
    except Exception as e:
        raise HTTPException(500, f"Failed to stop: {e}")
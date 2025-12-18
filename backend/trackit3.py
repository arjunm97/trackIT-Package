# trackit3.py
import argparse
import json
import signal
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime, timezone
import hashlib
from dotenv import load_dotenv


# ---- runtime state for clean shutdown ----
SHOULD_STOP = False

# ---- in-run dedupe state: cell_id -> last digest ----
LAST_DIGESTS = {}

def handle_signal(signum, frame):
    global SHOULD_STOP
    SHOULD_STOP = True
    print(f"[trackit3] Received signal {signum}, stopping...")

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def _iso_now():
    return datetime.now(timezone.utc).isoformat()

def _iso_from_epoch(sec: float):
    return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()

def _cell_id(cell, fallback_index: int):
    # nbformat >=4.5 usually has a stable 'id'
    return cell.get('id') or f"idx:{fallback_index}"

def _cell_digest(input_code: str, output_text: str):
    h = hashlib.sha256()
    h.update((input_code or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((output_text or "").encode("utf-8"))
    return h.hexdigest()

def _extract_io_from_cell(cell):
    input_code = ''.join(cell.get('source', []) or [])
    outputs = cell.get('outputs', []) or []

    # Collect text-like outputs
    output_text = ''
    for output in outputs:
        if isinstance(output, dict):
            if 'text' in output:
                output_text += ''.join(output['text'])
            elif 'data' in output and isinstance(output['data'], dict) and 'text/plain' in output['data']:
                output_text += ''.join(output['data']['text/plain'])
            elif 'ename' in output and 'evalue' in output:
                output_text += f"Error: {output.get('ename')}: {output.get('evalue')}\n"

    return input_code.strip(), output_text.strip()

def _extract_time_metadata(cell):
    meta = cell.get('metadata', {}) or {}
    # Try ExecuteTime nbextension first
    et = meta.get('ExecuteTime') or meta.get('execution') or {}
    start_time = et.get('start_time') or et.get('started') or None
    end_time = et.get('end_time') or et.get('finished') or None
    return start_time, end_time

def _append_jsonl(output_path: Path, record: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def _append_text(output_path: Path, record: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"# Snapshot {record['event_time']}")
    lines.append(f"- notebook_path: {record['notebook_path']}")
    lines.append(f"- notebook_mtime: {record['notebook_mtime']}")
    lines.append(f"- cell_index: {record['cell_index']}")
    lines.append(f"- cell_id: {record['cell_id']}")
    lines.append(f"- exec_count: {record.get('execution_count')}")
    lines.append(f"- exec_start: {record.get('exec_start')}")
    lines.append(f"- exec_end: {record.get('exec_end')}")
    lines.append("")
    lines.append("## Input:")
    lines.append(record['input'])
    lines.append("")
    lines.append("## Output:")
    lines.append(record['output'])
    lines.append("\n")
    with output_path.open('a', encoding='utf-8') as f:
        f.write("\n".join(lines))

def extract_inputs_outputs(notebook_path: Path, output_path: Path, as_json=False):
    """
    Appends only NEW cell states (based on content hash) with timestamps.
    Returns number of appended entries.
    """
    try:
        with notebook_path.open('r', encoding='utf-8') as f:
            notebook = json.load(f)
    except Exception as e:
        print(f"[trackit3] Error reading notebook: {e}")
        return 0

    event_time = _iso_now()
    try:
        stat = notebook_path.stat()
        notebook_mtime = _iso_from_epoch(stat.st_mtime)
    except Exception:
        notebook_mtime = None

    appended = 0
    cells = notebook.get('cells', []) or []
    for idx, cell in enumerate(cells):
        if cell.get('cell_type') != 'code':
            continue

        cell_input, cell_output = _extract_io_from_cell(cell)
        cid = _cell_id(cell, idx)
        digest = _cell_digest(cell_input, cell_output)
        if LAST_DIGESTS.get(cid) == digest:
            # No change for this cell since last snapshot
            continue

        exec_start, exec_end = _extract_time_metadata(cell)
        record = {
            "event_time": event_time,                
            "notebook_path": str(notebook_path),
            "notebook_mtime": notebook_mtime,
            "cell_index": idx + 1,
            "cell_id": cid,
            "execution_count": cell.get('execution_count'),
            "exec_start": exec_start,
            "exec_end": exec_end,
            "input": cell_input,
            "output": cell_output,
        }

        try:
            if as_json:
                _append_jsonl(output_path, record)   
            else:
                _append_text(output_path, record)    
            appended += 1
            LAST_DIGESTS[cid] = digest
        except Exception as e:
            print(f"[trackit3] Error appending output: {e}")

    print(f"[trackit3] Appended {appended} new cell snapshot(s) to {output_path}.")
    return appended

class NotebookChangeHandler(FileSystemEventHandler):
    def __init__(self, target_path: Path, output_path: Path, as_json: bool, debounce_sec: float):
        super().__init__()
        self.target_path = target_path
        self.target_name = target_path.name
        self.output_path = output_path
        self.as_json = as_json
        self.last_run = 0.0
        self.debounce_sec = debounce_sec

    def _maybe_process(self, event_path: str):
        p = Path(event_path)
        # Only process events for the target file
        try:
            if p.name != self.target_name and p.resolve() != self.target_path:
                return
        except Exception:
            if p.name != self.target_name:
                return

        now = time.monotonic()
        if now - self.last_run < self.debounce_sec:
            return
        self.last_run = now
        print(f"[trackit3] Detected change: {p}")
        extract_inputs_outputs(self.target_path, self.output_path, self.as_json)

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_process(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._maybe_process(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_process(event.dest_path)

def parse_args():
    ap = argparse.ArgumentParser(description="Watch a Jupyter notebook for changes and append input/output lineage.")
    ap.add_argument("--notebook", "-n", required=True, help="Path to .ipynb notebook to watch.")
    ap.add_argument("--output", "-o", required=True, help="Path to write the appended log (txt or jsonl when --json).")
    ap.add_argument("--json", action="store_true", help="Write output as JSON Lines (.jsonl), one record per cell.")
    ap.add_argument("--debounce", type=float, default=0.5, help="Debounce seconds for save events.")
    ap.add_argument("--once", action="store_true", help="Extract once and exit (no watching).")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    NOTEBOOK_PATH = Path(args.notebook).resolve()
    OUTPUT_PATH = Path(args.output).resolve()
    AS_JSON = bool(args.json)

    if not NOTEBOOK_PATH.exists():
        print(f"[trackit3] Notebook not found: {NOTEBOOK_PATH}")
        sys.exit(1)

    print(f"[trackit3] Using notebook: {NOTEBOOK_PATH}")
    print(f"[trackit3] Appending to  : {OUTPUT_PATH} (jsonl={AS_JSON})")

    # Initial pass (appends only new cell states)
    extract_inputs_outputs(NOTEBOOK_PATH, OUTPUT_PATH, AS_JSON)

    if args.once:
        sys.exit(0)

    # Watch mode
    event_handler = NotebookChangeHandler(NOTEBOOK_PATH, OUTPUT_PATH, AS_JSON, args.debounce)
    observer = Observer()
    observer.schedule(event_handler, path=str(NOTEBOOK_PATH.parent), recursive=False)

    observer.start()
    try:
        while not SHOULD_STOP:
            time.sleep(0.5)
    finally:
        observer.stop()
        observer.join()
        print("[trackit3] Stopped.")

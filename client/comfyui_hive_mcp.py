#!/usr/bin/env python3
"""MCP server (stdio) that lets a Claude session make images and videos on the ComfyUI-Hive rigs of the LAN.

It talks to each rig's chat page (page.py, port 8189), the same way the page in a browser does: it sends the request,
follows its progress, and saves what the rig made into a folder on this PC, so the session gets file paths back, never
the image or video itself. It never downloads a model onto a rig: that is done on the rig's page, by a person.

Environment:
  COMFYUI_HIVE_RIGS   The rigs' pages, comma separated (http://192.168.1.189:8189,...). A rig switched to another flight
                      sheet just stops answering and is skipped.
  COMFYUI_HIVE_OUT    Where results are saved. Default: the user's Videos folder, ComfyUI-Hive.
  COMFYUI_HIVE_ROOTS  More folders an image for image to video may be read from, besides the session's working
                      directory and COMFYUI_HIVE_OUT, separated by the OS path separator.

Standard library only, Python 3.8 or newer.
"""

import base64
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SERVER_NAME = "comfyui-hive"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
STATE_TIMEOUT_SECONDS = 4
DEFAULT_WAIT_MINUTES = 30
POLL_SECONDS = 2
MAX_IMAGE_BYTES = 40 * 1024 * 1024
TASK_NAMES = {"t2i": "text to image", "t2v": "text to video", "i2v": "image to video"}
# By extension: mimetypes knows no .webp on Windows with Python 3.8, and the registry can say image/pjpeg for .jpg
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_WAIT_MINUTES = 240
# Set when the session goes away (stdin closed): every wait ends
SHUTDOWN = threading.Event()

TOOLS = [
    {
        "name": "comfy_status",
        "description": (
            "Lists the ComfyUI-Hive rigs on the LAN: whether each answers, its GPU, which models are downloaded on it "
            "(with what each can make and the limits of its settings), which could be downloaded, and the requests "
            "running or waiting. Call it first to choose a model."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "comfy_generate",
        "description": (
            "Makes an image or a video on a ComfyUI-Hive rig and saves it on this PC; returns the saved file's path. "
            "task: t2i (text to image), t2v (text to video) or i2v (image to video, needs image). Only models already "
            "downloaded on a rig can be used: this never downloads one (if none has it, ask the user to press Download "
            "on the rig's page). Settings left out take the model's defaults; width, height, length (frames) or "
            "duration (seconds) must be within the limits comfy_status shows. A video takes minutes: with wait false "
            "it returns at once with a job to collect later with comfy_result."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What to make, described in full."},
                "model": {"type": "string", "description": "Model id from comfy_status, e.g. wan2.2-14b. Can be left out when only one downloaded model can do the task."},
                "task": {"type": "string", "enum": ["t2i", "t2v", "i2v"], "description": "Default: i2v when image is given, else t2v."},
                "image": {"type": "string", "description": "Path of the image to start from (i2v): PNG, JPEG or WebP."},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "length": {"type": "integer", "description": "Frames, for models that count frames."},
                "duration": {"type": "number", "description": "Seconds, for models that count seconds."},
                "seed": {"type": "integer", "description": "Default: random. The same seed and settings make the same result."},
                "rig": {"type": "string", "description": "A rig's address, to use that one. Default: the least busy rig that has the model."},
                "wait": {"type": "boolean", "description": "Wait for the result and save it (default true)."},
                "save_to": {"type": "string", "description": "Folder to save into. Default: the ComfyUI-Hive results folder."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "comfy_result",
        "description": (
            "Waits for a job started by comfy_generate (with wait false, or one that was still running when it "
            "returned), then saves its result on this PC and returns the path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "description": "The job id comfy_generate returned."},
                "rig": {"type": "string", "description": "The rig comfy_generate named."},
                "wait_minutes": {"type": "number", "description": "How long to wait before returning \"still running\". Default 30."},
                "save_to": {"type": "string", "description": "Folder to save into. Default: the ComfyUI-Hive results folder."},
            },
            "required": ["job", "rig"],
        },
    },
    {
        "name": "comfy_cancel",
        "description": "Stops a job: drops it if it is waiting, interrupts it if it is running.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string"}, "rig": {"type": "string"}},
            "required": ["job", "rig"],
        },
    },
]


class ToolError(Exception):
    pass


# --- rigs ---------------------------------------------------------------------------------------------------------

def rig_urls():
    configured = os.environ.get("COMFYUI_HIVE_RIGS", "")
    return [normalize(url) for url in configured.split(",") if url.strip()]


def normalize(rig):
    rig = rig.strip().rstrip("/")
    if not re.match(r"^https?://", rig):
        rig = "http://" + rig
    if not re.match(r"^https?://[^/]+:\d+$", rig):
        rig += ":8189"
    return rig


def resolve(rig):
    """A rig as the session named it, as the URL it is registered under: an address alone matches the registered
    rig with that address, whatever its port."""
    rig = str(rig)
    url = normalize(rig)
    registered = rig_urls()
    if url in registered:
        return url
    if not re.search(r":\d+$", rig.strip().rstrip("/").split("://")[-1]):
        host = urllib.parse.urlparse(url).hostname
        matches = [u for u in registered if urllib.parse.urlparse(u).hostname == host]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ToolError("{} is several registered rigs: {}. Give the port too.".format(rig, ", ".join(matches)))
    raise ToolError("{} is not a registered rig. Registered: {}".format(rig, ", ".join(registered) or "none"))


def request(url, payload=None, timeout=STATE_TIMEOUT_SECONDS):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read().decode("utf-8")).get("error")
        except ValueError:
            message = None
        raise ToolError(message or "{} answered HTTP {}".format(url, error.code))
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
        # Not answering, or something that isn't the rig's page answering on its port
        raise ToolError("{} doesn't answer as a ComfyUI-Hive page ({}): is that rig on the ComfyUI-Hive flight sheet?"
                        .format(url.split("/api/")[0], getattr(error, "reason", error)))
    if not isinstance(answer, dict):
        raise ToolError("{} doesn't answer as a ComfyUI-Hive page".format(url.split("/api/")[0]))
    return answer


def rig_state(url):
    """The rig's /api/state, or None if it doesn't answer (another flight sheet, rented, off)."""
    try:
        return request(url + "/api/state")
    except ToolError:
        return None


def all_states():
    urls = rig_urls()
    if not urls:
        raise ToolError("No ComfyUI-Hive rigs are registered on this PC: run client\\comfyui-hive.cmd add <address>")
    return [(url, rig_state(url)) for url in urls]


def busy(state):
    return sum(1 for job in state.get("jobs", []) if job.get("state") in ("queued", "running"))


def gb(number):
    return "{:.1f} GB".format((number or 0) / 1024 ** 3)


def describe_inputs(inputs):
    parts = []
    for item in inputs:
        if item["name"] in ("prompt", "image"):
            continue
        limits = ""
        if item.get("min") is not None or item.get("max") is not None:
            limits = " {}-{}".format(item.get("min", ""), item.get("max", ""))
            if item.get("step") and item["step"] != 1:
                limits += " step {}".format(item["step"])
        parts.append("{}={}{}".format(item["name"], item.get("default", "?"), limits))
    return ", ".join(parts)


def status(_arguments):
    lines = []
    for url, state in all_states():
        if state is None:
            lines.append("{}: not answering (fine if that rig is on another flight sheet)".format(url))
            continue
        gpu = state.get("gpu") or {}
        lines.append("{}: {}, {} GB, ComfyUI {}, {} request(s) running or waiting, {} free".format(
            url, gpu.get("name", "no GPU"), gpu.get("vram_gb", "?"), state.get("state"), busy(state),
            gb(state.get("disk_free"))))
        for model in state.get("models", []):
            if model.get("installed"):
                lines.append("  {} ({}, {}): downloaded".format(model["id"], model["name"], model["variant"]))
                for task, inputs in model["tasks"].items():
                    lines.append("    {} {}: {}".format(task, TASK_NAMES.get(task, task), describe_inputs(inputs)))
            else:
                download = model.get("download") or {}
                doing = " (downloading now)" if download.get("state") in ("queued", "downloading") else ""
                lines.append("  {} ({}): not downloaded{}, {} to download on the rig's page; can do {}".format(
                    model["id"], model["name"], doing, gb(model.get("to_download")), ", ".join(model["tasks"])))
        for job in state.get("jobs", []):
            if job.get("state") in ("queued", "running"):
                lines.append("  job {} {}: {} {} \"{}\"".format(job["id"], job["state"], job["model"], job["task"],
                                                             job["prompt"][:60]))
    return "\n".join(lines)


def choose(arguments, task):
    """The rig and model to use: (url, state, model)."""
    wanted_rig = resolve(arguments["rig"]) if arguments.get("rig") else None
    wanted_model = arguments.get("model")
    candidates, elsewhere = [], []
    for url, state in all_states():
        if state is None or (wanted_rig and url != wanted_rig):
            continue
        for model in state.get("models", []):
            if task not in model["tasks"] or (wanted_model and model["id"] != wanted_model):
                continue
            (candidates if model.get("installed") else elsewhere).append((url, state, model))
    if not candidates:
        if elsewhere:
            names = ", ".join(sorted({"{} on {}".format(m["id"], u) for u, _, m in elsewhere}))
            raise ToolError("No rig has a model for {} downloaded yet. It can be downloaded on the rig's page "
                            "(ask the user to press Download there): {}".format(TASK_NAMES.get(task, task), names))
        what = "model {}".format(wanted_model) if wanted_model else "any model for {}".format(TASK_NAMES.get(task, task))
        raise ToolError("No answering rig{} offers {}. comfy_status lists what each rig has.".format(
            " " + wanted_rig if wanted_rig else "", what))
    if not wanted_model and len({m["id"] for _, _, m in candidates}) > 1:
        raise ToolError("Several downloaded models can do {}: {}. Say which with model.".format(
            TASK_NAMES.get(task, task), ", ".join(sorted({m["id"] for _, _, m in candidates}))))
    # The least busy rig; ties go to the first registered
    return min(candidates, key=lambda c: busy(c[1]))


# --- files on this PC ---------------------------------------------------------------------------------------------

def out_folder(override=None):
    if override:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(override)))
    configured = os.environ.get("COMFYUI_HIVE_OUT")
    if configured:
        return os.path.abspath(os.path.expandvars(configured))
    return os.path.join(os.path.expanduser("~"), "Videos", "ComfyUI-Hive")


def roots():
    folders = [os.getcwd(), out_folder()] + os.environ.get("COMFYUI_HIVE_ROOTS", "").split(os.pathsep)
    return [os.path.realpath(os.path.expandvars(folder)) for folder in folders if folder]


def read_image(path):
    """The image as a data URL, if it is in a folder this server may read."""
    full = os.path.realpath(os.path.abspath(os.path.expandvars(os.path.expanduser(str(path)))))
    if not any(full == root or full.startswith(root.rstrip(os.sep) + os.sep) for root in roots()):
        raise ToolError("{} is outside the folders this tool may read ({}). Copy it into the working directory "
                        "first.".format(path, "; ".join(roots())))
    kind = IMAGE_TYPES.get(os.path.splitext(full)[1].lower())
    if kind is None:
        raise ToolError("{} is not a PNG, JPEG or WebP image".format(path))
    try:
        size = os.path.getsize(full)
        if size > MAX_IMAGE_BYTES:
            raise ToolError("{} is too big ({} MB, 40 MB at most)".format(path, size // 1024 ** 2))
        with open(full, "rb") as handle:
            data = handle.read()
    except OSError as error:
        raise ToolError("Can't read {}: {}".format(path, error))
    return "data:{};base64,{}".format(kind, base64.b64encode(data).decode("ascii"))


def save_outputs(url, job, folder):
    os.makedirs(folder, exist_ok=True)
    saved = []
    root = os.path.realpath(folder)
    for relative in job.get("outputs", []):
        name = str(relative).replace("\\", "/").split("/")[-1]
        target = os.path.join(root, name)
        # Only a plain file name, landing in the folder: never another drive (C:x), a stream (x:y) or ..
        if not name or ":" in name or name in (".", "..") or os.path.dirname(os.path.realpath(target)) != root:
            raise ToolError("The rig gave an output name that can't be saved safely: {!r}".format(relative))
        file_url = "{}/files/{}?download=1".format(url, urllib.parse.quote(str(relative)))
        part = target + ".part"
        try:
            written = 0
            with urllib.request.urlopen(file_url, timeout=60) as response, open(part, "wb") as handle:
                expected = response.headers.get("Content-Length")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
                    written += len(block)
            if expected is not None and written != int(expected):
                raise OSError("got {} of {} bytes: the connection to the rig dropped".format(written, expected))
            os.replace(part, target)
        except (OSError, http.client.HTTPException, ValueError) as error:
            try:
                os.remove(part)
            except OSError:
                pass
            raise ToolError("The rig made {} but it couldn't be saved here: {}. It is on the rig's page: {}".format(
                name, error, url))
        saved.append(target)
    return saved


# --- jobs ---------------------------------------------------------------------------------------------------------

class Progress:
    """MCP progress notifications, when the client asked for them (a progressToken in the request)."""

    def __init__(self, token):
        self.token = token
        self.last = None
        self.count = 0

    def __call__(self, message):
        # MCP wants progress to only go up, and a job's steps start again for each sampler of a workflow: so the value
        # counts the updates, and the step is in the message
        if self.token is None or message == self.last:
            return
        self.last = message
        self.count += 1
        write({"jsonrpc": "2.0", "method": "notifications/progress",
               "params": {"progressToken": self.token, "progress": self.count, "message": message}})


class Cancelled(Exception):
    """The session cancelled the tool call, or went away."""


def find_job(url, job_id):
    """The job, or None if the rig doesn't answer; a ToolError if it answers without the job."""
    state = rig_state(url)
    if state is None:
        return None
    job = next((job for job in state.get("jobs", []) if isinstance(job, dict) and job.get("id") == job_id), None)
    if job is None:
        raise ToolError("{} has no job {} (it keeps the last 60). comfy_status lists the ones running.".format(
            url, job_id))
    return job


def wait_for(url, job_id, minutes, progress, stop):
    """The job once it has ended, or None if it is still going after `minutes`."""
    deadline = time.time() + minutes * 60
    missing_since = None
    while True:
        if stop.is_set() or SHUTDOWN.is_set():
            raise Cancelled()
        job = find_job(url, job_id)
        if job is None:
            # The rig not answering for a while: restarted, switched flight sheet, or rented
            missing_since = missing_since or time.time()
            if time.time() - missing_since > 120:
                raise ToolError("{} stopped answering while job {} was running. If it comes back, comfy_result "
                                "can still collect it.".format(url, job_id))
        else:
            missing_since = None
            if job.get("state") in ("done", "failed", "cancelled"):
                # The rig sets the state a moment before the finishing time and the error: read it once more
                if not job.get("finished"):
                    stop.wait(1)
                    job = find_job(url, job_id) or job
                return job
            if job.get("state") == "queued":
                progress("waiting in the rig's queue")
            elif job.get("steps"):
                speed = job.get("it_s") or 0
                pace = " ({:.2f} it/s)".format(speed) if speed >= 1 else (" ({:.1f} s/step)".format(1 / speed) if speed else "")
                progress("step {}/{}{}".format(job.get("step", 0), job["steps"], pace))
            else:
                progress(job.get("note") or "loading the model")
        if time.time() > deadline:
            return None
        stop.wait(POLL_SECONDS)


def report(url, job, folder):
    if job["state"] == "cancelled":
        return "Job {} was cancelled.".format(job["id"])
    if job["state"] == "failed":
        raise ToolError("The rig couldn't make it: {}".format(job.get("error") or "no reason given"))
    saved = save_outputs(url, job, folder)
    took = ""
    if job.get("finished") and job.get("started"):
        took = ", {} s".format(round(job["finished"] - job["started"]))
    lines = ["Saved: " + path for path in saved]
    lines.append("{} {} on {}, seed {}{}.".format(job.get("model"), job.get("variant"), url, job.get("seed"), took))
    if job.get("values"):
        lines.append("Settings: " + ", ".join("{}={}".format(k, v) for k, v in job["values"].items()))
    return "\n".join(lines)


def still_running(url, job_id):
    return ("Job {} is still running on {}. Collect it later with comfy_result (job {}, rig {}); it is also on the "
            "rig's page.".format(job_id, url, job_id, url))


def generate(arguments, progress, stop):
    prompt = str(arguments.get("prompt") or "").strip()
    if not prompt:
        raise ToolError("prompt is empty")
    task = arguments.get("task") or ("i2v" if arguments.get("image") else "t2v")
    if task not in TASK_NAMES:
        raise ToolError("task must be t2i, t2v or i2v")
    url, _state, model = choose(arguments, task)
    names = {item["name"] for item in model["tasks"][task]}
    body = {"model": model["id"], "task": task, "prompt": prompt}
    if "image" in names:
        if not arguments.get("image"):
            raise ToolError("{} {} needs image: the path of a picture to start from".format(model["id"], task))
        body["image"] = read_image(arguments["image"])
    elif arguments.get("image"):
        raise ToolError("{} {} doesn't take an image; use task i2v".format(model["id"], task))
    ignored = []
    for name in ("width", "height", "length", "duration", "seed"):
        if arguments.get(name) is None:
            continue
        if name == "seed" or name in names:
            body[name] = arguments[name]
        else:
            ignored.append(name)
    job_id = request(url + "/api/generate", body, timeout=60)["job"]
    note = " ({} doesn't take {}: left out)".format(model["id"], ", ".join(ignored)) if ignored else ""
    if arguments.get("wait") is False:
        return "Started job {} on {}{}. Collect it with comfy_result.".format(job_id, url, note)
    try:
        job = wait_for(url, job_id, DEFAULT_WAIT_MINUTES, progress, stop)
    except Cancelled:
        return "Stopped waiting; job {} goes on on {}. comfy_result collects it, comfy_cancel stops it.".format(
            job_id, url)
    if job is None:
        return still_running(url, job_id) + note
    return report(url, job, out_folder(arguments.get("save_to"))) + note


def result(arguments, progress, stop):
    url = resolve(arguments["rig"])
    minutes = arguments.get("wait_minutes")
    try:
        minutes = DEFAULT_WAIT_MINUTES if minutes is None else min(MAX_WAIT_MINUTES, max(0.0, float(minutes)))
    except (TypeError, ValueError):
        raise ToolError("wait_minutes must be a number")
    try:
        job = wait_for(url, str(arguments["job"]), minutes, progress, stop)
    except Cancelled:
        return "Stopped waiting; job {} goes on on {}.".format(arguments["job"], url)
    if job is None:
        return still_running(url, arguments["job"])
    return report(url, job, out_folder(arguments.get("save_to")))


def cancel(arguments, _progress, _stop):
    url = resolve(arguments["rig"])
    request(url + "/api/cancel", {"job": arguments["job"]})
    return "Asked {} to stop job {}.".format(url, arguments["job"])


HANDLERS = {
    "comfy_status": lambda arguments, _progress, _stop: status(arguments),
    "comfy_generate": generate,
    "comfy_result": result,
    "comfy_cancel": cancel,
}


# --- MCP over stdio -----------------------------------------------------------------------------------------------

WRITE_LOCK = threading.Lock()
# Tool calls in progress: request id -> the event that stops their wait
RUNNING = {}


def write(message):
    with WRITE_LOCK:
        sys.stdout.buffer.write(json.dumps(message).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()


def call_tool(request_id, params, stop):
    handler = HANDLERS.get(params.get("name"))
    if handler is None:
        RUNNING.pop(request_id, None)
        write({"jsonrpc": "2.0", "id": request_id,
               "error": {"code": -32602, "message": "Unknown tool: {}".format(params.get("name"))}})
        return
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    progress = Progress(meta.get("progressToken"))
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    try:
        body = {"content": [{"type": "text", "text": handler(arguments, progress, stop)}]}
    except ToolError as error:
        body = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    except Exception as error:  # noqa: BLE001 - a broken answer from a rig must not end the server
        body = {"content": [{"type": "text", "text": "Failed: {}: {}".format(type(error).__name__, error)}],
                "isError": True}
    finally:
        RUNNING.pop(request_id, None)
    write({"jsonrpc": "2.0", "id": request_id, "result": body})


def handle(message):
    """Answers one JSON-RPC message. Tool calls run on their own thread, so a long wait doesn't hold up the others,
    and a cancellation from the session stops it."""
    if not isinstance(message, dict):
        write({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Not a JSON-RPC request"}})
        return
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "notifications/cancelled":
        stop = RUNNING.get(params.get("requestId"))
        if stop is not None:
            stop.set()
        return
    if request_id is None:
        return
    if method == "initialize":
        body = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}
    elif method == "ping":
        body = {}
    elif method == "tools/list":
        body = {"tools": TOOLS}
    elif method == "tools/call":
        stop = RUNNING[request_id] = threading.Event()
        threading.Thread(target=call_tool, args=(request_id, params, stop), daemon=True).start()
        return
    else:
        write({"jsonrpc": "2.0", "id": request_id,
               "error": {"code": -32601, "message": "Method not found: {}".format(method)}})
        return
    write({"jsonrpc": "2.0", "id": request_id, "result": body})


def main():
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            message = json.loads(line.decode("utf-8"))
        except ValueError as error:
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}})
            continue
        try:
            handle(message)
        except Exception as error:  # noqa: BLE001 - the server stays up for the next message
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(error)}})
    # The session is gone: end the waits, so the process doesn't linger
    SHUTDOWN.set()
    for stop in list(RUNNING.values()):
        stop.set()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""The rig's chat page: pick a model, type a prompt, get an image or a video back to watch and download.

h-run.sh runs it beside ComfyUI, on the rig's LAN address at ComfyUI's port + 1. It does the miner's work:

- lists the models of catalog.json that fit this rig's GPU, each with the build (precision, quantization) that fits it,
  and hides the rest;
- downloads a model's files only when someone presses Download on the page, into the models folder that ComfyUI reads,
  resuming a file that was cut off; deletes them when asked;
- turns a request into the model's workflow (workflows/<model>-<task>.json, made by tools/build.py), sends it to
  ComfyUI, follows its progress, and keeps the outputs and the history of requests;
- writes what it is doing to --page-file for h-stats.sh, so the Hive dashboard shows it too.

  /               the page (page.html)
  /api/state      the rig, its models, the jobs, what is happening now
  /api/generate   POST {model, task, prompt, image?, width?, height?, length?, seed?}: queues a job
  /api/cancel     POST {job}: drops a queued job or stops the running one
  /api/download   POST {model}: downloads the model's files; /api/cancel-download and /api/delete likewise
  /api/token      POST {token}: the Hugging Face token for gated models, kept on the rig
  /files/<path>   an output, ?download=1 to save it
  /log            the end of the miner log

Anything that can reach the port can use it: like ComfyUI itself, it listens only on the private LAN address, and the
firewall rules of h-run.sh limit it to allow=. Standard library only, so it runs before ComfyUI's packages are installed.
"""

import argparse
import base64
import copy
import hashlib
import http.server
import json
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CHUNK = 4 * 1024 * 1024
KEEP_JOBS = 500
MAX_UPLOAD = 40 * 1024 * 1024
SPARE_DISK = 2 * 1024 ** 3  # left free on the data drive after a download
OUTPUT_PREFIX = "comfyui-hive"

args = None
lock = threading.RLock()
wake_jobs = threading.Condition(lock)
wake_downloads = threading.Condition(lock)


def log(message):
    print(f"[comfyui-hive page] {time.strftime('%F %T')} {message}", flush=True)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    os.replace(temp, path)


def read_line(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


# --- the rig ------------------------------------------------------------------------------------------------------

def gpu_info():
    """The GPU ComfyUI runs on: name, memory in GB, compute capability, and its memory and load now."""
    try:
        line = subprocess.run(
            ["nvidia-smi", "-i", str(args.gpu), "--query-gpu=name,memory.total,memory.used,compute_cap,utilization.gpu,"
             "temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        name, total, used, cap, load, temp, power = [part.strip() for part in line.split(",")]
        return {"name": name, "vram_gb": round(int(total) / 1024, 1), "used_gb": round(int(used) / 1024, 1),
                "compute": float(cap), "load": load, "temp": temp, "power": power}
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return None


def ram_gb():
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 ** 2, 1)
    except (OSError, ValueError):
        pass
    return None


def disk_free():
    try:
        return shutil.disk_usage(args.models).free
    except OSError:
        return 0


# --- models -------------------------------------------------------------------------------------------------------

def load_catalog():
    return read_json(args.catalog, {"models": []})


def pick_variant(model, gpu):
    """The best build of a model that fits this GPU, or None. Variants are listed best first."""
    if gpu is None:
        return None
    for variant in model["variants"]:
        if gpu["vram_gb"] + 0.5 < variant.get("min_vram_gb", 0):
            continue
        if gpu["compute"] < variant.get("min_compute", 0):
            continue
        return variant
    return None


def file_path(entry):
    return os.path.join(args.models, entry["dir"], entry["name"])


def file_present(entry):
    try:
        size = os.path.getsize(file_path(entry))
    except OSError:
        return False
    return not entry.get("size") or size == entry["size"]


def model_files(model, variant):
    return [model["files"][name] for name in variant["files"]]


class Rig:
    """What changes: the downloads, the jobs, and the numbers for the dashboard."""

    def __init__(self):
        os.makedirs(args.data, exist_ok=True)
        self.catalog = load_catalog()
        self.gpu = gpu_info()
        self.ram = ram_gb()
        self.downloads = {}  # model id -> {state, done, total, file, error, speed}
        self.download_queue = []
        self.jobs = []
        self.done = 0
        self.failed = 0
        self.settings = read_json(os.path.join(args.data, "settings.json"), {})
        self.token = read_line(os.path.join(args.data, "hf_token")) or os.environ.get("HF_TOKEN", "")
        self.last_model = None
        for line in self.read_jobs():
            if line.get("state") in ("queued", "running"):
                line["state"] = "failed"
                line["error"] = "The miner stopped before this was done"
            self.jobs.append(line)

    # models ---

    def models(self):
        """Every model that fits this GPU, with its build and whether it is here."""
        out = []
        for model in self.catalog["models"]:
            variant = pick_variant(model, self.gpu)
            if variant is None:
                continue
            files = model_files(model, variant)
            missing = [f for f in files if not file_present(f)]
            size = sum(f.get("size") or 0 for f in files)
            to_get = sum(f.get("size") or 0 for f in missing)
            out.append({
                "id": model["id"], "name": model["name"], "about": model.get("about", ""),
                "note": model.get("note", ""), "gated": model.get("gated", ""),
                "variant": variant["label"], "variant_note": variant.get("note", ""),
                "tasks": {task: spec["inputs"] for task, spec in model["tasks"].items()},
                "size": size, "to_download": to_get, "installed": not missing,
                "download": self.downloads.get(model["id"]),
            })
        return out

    def find_model(self, model_id):
        for model in self.catalog["models"]:
            if model["id"] == model_id:
                variant = pick_variant(model, self.gpu)
                if variant is not None:
                    return model, variant
        return None, None

    def start_download(self, model_id):
        model, variant = self.find_model(model_id)
        if model is None:
            return "No such model for this GPU"
        if model.get("gated") and not self.token:
            return (f"{model['name']} needs a Hugging Face token: accept the license at {model['gated']} with your "
                    "account, then give the token on this page or as hf_token= in the flight sheet")
        missing = [f for f in model_files(model, variant) if not file_present(f)]
        need = sum(f.get("size") or 0 for f in missing)
        if need + SPARE_DISK > disk_free():
            return f"Not enough free space: it needs {need / 1024 ** 3:.1f} GB and {disk_free() / 1024 ** 3:.1f} GB is free"
        with lock:
            current = self.downloads.get(model_id)
            if current and current["state"] in ("queued", "downloading"):
                return None
            self.downloads[model_id] = {"state": "queued", "done": 0, "total": need, "file": "", "error": "",
                                        "speed": 0}
            self.download_queue.append(model_id)
            wake_downloads.notify_all()
        log(f"Download of {model['name']} ({variant['label']}) asked for: {need / 1024 ** 3:.1f} GB")
        return None

    def cancel_download(self, model_id):
        with lock:
            current = self.downloads.get(model_id)
            if current and current["state"] in ("queued", "downloading"):
                current["state"] = "cancelled"
                if model_id in self.download_queue:
                    self.download_queue.remove(model_id)

    def delete_model(self, model_id):
        model, variant = self.find_model(model_id)
        if model is None:
            return "No such model for this GPU"
        with lock:
            current = self.downloads.get(model_id)
            if current and current["state"] in ("queued", "downloading"):
                return "It is downloading: cancel that first"
            if any(j["state"] in ("queued", "running") and j["model"] == model_id for j in self.jobs):
                return "A request is using it"
        # Files another downloaded model also uses stay
        keep = set()
        for other in self.catalog["models"]:
            if other["id"] == model_id:
                continue
            other_variant = pick_variant(other, self.gpu)
            if other_variant is None:
                continue
            files = model_files(other, other_variant)
            if all(file_present(f) for f in files):
                keep.update(file_path(f) for f in files)
        freed = 0
        for entry in model_files(model, variant):
            path = file_path(entry)
            if path in keep:
                continue
            for candidate in (path, path + ".part"):
                try:
                    freed += os.path.getsize(candidate)
                    os.remove(candidate)
                except OSError:
                    pass
        with lock:
            self.downloads.pop(model_id, None)
        log(f"Deleted {model['name']}: {freed / 1024 ** 3:.1f} GB freed")
        return None

    def download_loop(self):
        while True:
            with lock:
                while not self.download_queue:
                    wake_downloads.wait()
                model_id = self.download_queue.pop(0)
                status = self.downloads[model_id]
                if status["state"] == "cancelled":
                    continue
                status["state"] = "downloading"
            model, variant = self.find_model(model_id)
            try:
                for entry in model_files(model, variant):
                    if file_present(entry):
                        continue
                    self.download_file(entry, status)
                    if status["state"] == "cancelled":
                        break
                if status["state"] != "cancelled":
                    status["state"] = "done"
                    log(f"Downloaded {model['name']}")
            except Exception as error:  # noqa: BLE001 - whatever stopped it is said on the page
                status["state"] = "failed"
                status["error"] = str(error)
                log(f"Download of {model['name']} failed: {error}")

    def download_file(self, entry, status):
        path = file_path(entry)
        part = path + ".part"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        have = os.path.getsize(part) if os.path.exists(part) else 0
        status["file"] = entry["name"]
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "comfyui-hive"})
        if have:
            request.add_header("Range", f"bytes={have}-")
        if self.token and urllib.parse.urlparse(entry["url"]).hostname == "huggingface.co":
            # Not passed on to the storage the download is redirected to
            request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code == 416 and entry.get("size") and have == entry["size"]:
                os.replace(part, path)
                return
            if error.code in (401, 403):
                raise RuntimeError(f"{entry['name']}: access denied ({error.code}). Accept the model's license on "
                                   "Hugging Face with the account of the token, and check the token") from error
            raise RuntimeError(f"{entry['name']}: HTTP {error.code}") from error
        if have and response.status != 206:
            have = 0  # the server sent the whole file
        status["done"] += have
        started, counted = time.time(), 0
        with response, open(part, "ab" if have else "wb") as handle:
            while True:
                if status["state"] == "cancelled":
                    return
                block = response.read(CHUNK)
                if not block:
                    break
                handle.write(block)
                status["done"] += len(block)
                counted += len(block)
                status["speed"] = counted / max(0.1, time.time() - started)
        size = os.path.getsize(part)
        if entry.get("size") and size != entry["size"]:
            raise RuntimeError(f"{entry['name']}: got {size} bytes of {entry['size']}, will resume on the next try")
        os.replace(part, path)

    # jobs ---

    def read_jobs(self):
        jobs = []
        try:
            with open(os.path.join(args.data, "jobs.jsonl"), encoding="utf-8") as handle:
                for line in handle:
                    try:
                        jobs.append(json.loads(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        return jobs[-KEEP_JOBS:]

    def save_jobs(self):
        path = os.path.join(args.data, "jobs.jsonl")
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            for job in self.jobs[-KEEP_JOBS:]:
                handle.write(json.dumps(job) + "\n")
        os.replace(path + ".tmp", path)

    def add_job(self, request):
        model, variant = self.find_model(request.get("model"))
        if model is None:
            return None, "That model doesn't fit this rig's GPU"
        if not all(file_present(f) for f in model_files(model, variant)):
            return None, f"{model['name']} isn't downloaded on this rig yet: press Download first"
        task = request.get("task")
        if task not in model["tasks"]:
            return None, f"{model['name']} can't do {task}"
        prompt = str(request.get("prompt") or "").strip()
        if not prompt:
            return None, "Write a prompt"
        spec = model["tasks"][task]
        job = {"id": f"{time.strftime('%Y%m%d-%H%M%S')}-{random.randrange(16 ** 4):04x}", "model": model["id"],
               "model_name": model["name"], "variant": variant["label"], "task": task, "prompt": prompt,
               "state": "queued", "created": time.time(), "outputs": [], "error": "", "values": {}}
        for item in spec["inputs"]:
            name = item["name"]
            if name in ("prompt", "image") or name not in request or request[name] in ("", None):
                continue
            try:
                value = float(request[name]) if item["kind"] == "float" else int(request[name])
            except (TypeError, ValueError):
                return None, f"{name} must be a number"
            low, high = item.get("min"), item.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                return None, f"{name} must be between {low} and {high}"
            job["values"][name] = value
        if any(i["name"] == "image" for i in spec["inputs"]):
            image = request.get("image") or ""
            match = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", image, re.S)
            if not match:
                return None, "This needs an image: attach one"
            data = base64.b64decode(match.group(2))
            if len(data) > MAX_UPLOAD:
                return None, "The image is too big"
            name = f"{job['id']}.{'jpg' if match.group(1) == 'jpeg' else match.group(1)}"
            with open(os.path.join(args.inputs, name), "wb") as handle:
                handle.write(data)
            job["image"] = name
        if request.get("seed") not in (None, ""):
            try:
                job["seed"] = int(request["seed"])
            except (TypeError, ValueError):
                return None, "seed must be a number"
        with lock:
            self.jobs.append(job)
            self.settings = {"model": model["id"], "task": task}
            write_json(os.path.join(args.data, "settings.json"), self.settings)
            self.save_jobs()
            wake_jobs.notify_all()
        log(f"Job {job['id']}: {model['name']} {task}: {prompt[:120]}")
        return job, None

    def cancel_job(self, job_id):
        with lock:
            for job in self.jobs:
                if job["id"] != job_id:
                    continue
                if job["state"] == "queued":
                    job["state"] = "cancelled"
                    self.save_jobs()
                elif job["state"] == "running":
                    job["cancel"] = True
                    try:
                        comfy_post("/interrupt", {})
                    except OSError:
                        pass
                return

    def job_loop(self):
        while True:
            with lock:
                job = None
                while job is None:
                    job = next((j for j in self.jobs if j["state"] == "queued"), None)
                    if job is None:
                        wake_jobs.wait()
                job["state"] = "running"
                job["started"] = time.time()
                job["step"], job["steps"], job["it_s"] = 0, 0, 0
                self.save_jobs()
            try:
                self.run_job(job)
                job["state"] = "cancelled" if job.get("cancel") else "done"
                if job["state"] == "done":
                    self.done += 1
            except Exception as error:  # noqa: BLE001 - said on the page and in the log
                job["state"] = "cancelled" if job.get("cancel") else "failed"
                job["error"] = str(error)
                if job["state"] == "failed":
                    self.failed += 1
                log(f"Job {job['id']} failed: {error}")
            job["finished"] = time.time()
            job.pop("cancel", None)
            with lock:
                self.save_jobs()

    def run_job(self, job):
        if read_line(args.state_file) != "ready":
            job["note"] = "Waiting for ComfyUI to start"
            while read_line(args.state_file) != "ready":
                if job.get("cancel"):
                    raise RuntimeError("cancelled")
                time.sleep(2)
            job["note"] = ""
        model, variant = self.find_model(job["model"])
        if model is None:
            raise RuntimeError("The model is no longer offered on this rig")
        prompt = build_prompt(model, variant, job)
        if self.last_model and self.last_model != job["model"]:
            # Another model: let go of the last one's memory first rather than squeezing both
            comfy_post("/free", {"unload_models": True, "free_memory": True})
        self.last_model = job["model"]
        client_id = hashlib.sha1(job["id"].encode()).hexdigest()
        watcher = ProgressWatcher(client_id, job)
        watcher.start()
        try:
            answer = comfy_post("/prompt", {"prompt": prompt, "client_id": client_id})
        except urllib.error.HTTPError as error:
            raise RuntimeError(describe_rejection(error)) from error
        prompt_id = answer["prompt_id"]
        watcher.prompt_id = prompt_id
        # The websocket says when it ends; /history says it too, for when the websocket can't be had
        while True:
            history = comfy_get(f"/history/{prompt_id}").get(prompt_id)
            if history and history.get("status", {}).get("completed") is not None \
                    and (history["status"].get("completed") or history["status"].get("status_str") == "error"):
                break
            if history and history.get("status", {}).get("status_str") == "error":
                break
            time.sleep(1)
        watcher.stop()
        status = history.get("status", {})
        if status.get("status_str") == "error" or not status.get("completed"):
            raise RuntimeError(execution_error(status) or "ComfyUI could not finish it")
        for node_output in history.get("outputs", {}).values():
            for key in ("images", "gifs", "videos", "audio"):
                for item in node_output.get(key, []) or []:
                    if item.get("type") != "output":
                        continue
                    relative = os.path.join(item.get("subfolder", ""), item["filename"]).replace(os.sep, "/")
                    if relative not in job["outputs"]:
                        job["outputs"].append(relative)
        if not job["outputs"]:
            raise RuntimeError("ComfyUI finished without saving anything")

    # dashboard ---

    def activity(self):
        with lock:
            running = next((j for j in self.jobs if j["state"] == "running"), None)
            downloading = next(((k, d) for k, d in self.downloads.items() if d["state"] == "downloading"), None)
        page = {"done": self.done, "failed": self.failed, "generating": running is not None}
        if running:
            page["it_s"] = running.get("it_s", 0)
            step = f" {running.get('step', 0)}/{running['steps']}" if running.get("steps") else ""
            page["activity"] = f"generating{step} {running['model']} {running['task']}"
        elif downloading:
            model_id, status = downloading
            percent = int(100 * status["done"] / status["total"]) if status["total"] else 0
            page["activity"] = f"downloading {model_id} {percent}%"
        else:
            page["activity"] = "ready"
        return page

    def stats_loop(self):
        tick = 0
        while True:
            try:
                write_json(args.page_file, self.activity())
                tick += 1
                if tick % 5 == 0:
                    self.gpu = gpu_info() or self.gpu
            except OSError:
                pass
            time.sleep(2)

    def state(self):
        with lock:
            jobs = [{k: v for k, v in j.items() if k != "cancel"} for j in self.jobs[-60:]]
        return {
            "version": args.version, "state": read_line(args.state_file) or "stopped",
            "comfy_url": args.comfy, "gpu": self.gpu, "ram_gb": self.ram,
            "disk_free": disk_free(), "models": self.models(), "jobs": jobs,
            "settings": self.settings, "has_token": bool(self.token),
            "hidden": len(self.catalog["models"]) - len(self.models()),
        }


# --- ComfyUI ------------------------------------------------------------------------------------------------------

def comfy_get(path):
    with urllib.request.urlopen(args.comfy + path, timeout=30) as response:
        return json.load(response)


def comfy_post(path, body):
    request = urllib.request.Request(args.comfy + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read()
    return json.loads(text) if text.strip() else {}


def describe_rejection(error):
    """ComfyUI's reason for refusing a workflow, in a line."""
    try:
        body = json.loads(error.read())
    except (ValueError, OSError):
        return f"ComfyUI refused the request (HTTP {error.code})"
    parts = [body.get("error", {}).get("message", "")]
    for node_id, node in (body.get("node_errors") or {}).items():
        for item in node.get("errors", []):
            parts.append(f"{node.get('class_type', node_id)}: {item.get('message')} {item.get('details', '')}".strip())
    return "ComfyUI refused it: " + "; ".join(p for p in parts if p)


def execution_error(status):
    for name, data in status.get("messages", []):
        if name == "execution_error":
            return f"{data.get('node_type', '')}: {data.get('exception_message', '').strip()}"
    return ""


def build_prompt(model, variant, job):
    """The model's workflow with this job's prompt, settings and build filled in."""
    task = model["tasks"][job["task"]]
    with open(os.path.join(args.workflows, task["workflow"]), encoding="utf-8") as handle:
        workflow = json.load(handle)
    prompt = workflow["prompt"]
    params = workflow["params"]
    replace = variant.get("replace", {})
    for node in prompt.values():
        for name, value in list(node["inputs"].items()):
            if isinstance(value, str) and value in replace:
                node["inputs"][name] = replace[value]

    def put(label, value):
        for node_id, name in params.get(label, []):
            prompt[node_id]["inputs"][name] = value

    for node_id, name, value in variant.get("set", []):
        prompt[node_id]["inputs"][name] = value
    for item in task["inputs"]:
        name = item["name"]
        if name == "prompt":
            put(item["param"], job["prompt"])
        elif name == "image":
            for node in prompt.values():
                if node["class_type"] == "LoadImage":
                    node["inputs"]["image"] = job["image"]
        elif name in job["values"]:
            put(item["param"], job["values"][name])
    seed = job.get("seed")
    if seed is None:
        seed = random.randrange(2 ** 50)
        job["seed"] = seed
    for node in prompt.values():
        for name in ("seed", "noise_seed"):
            if isinstance(node["inputs"].get(name), int):
                node["inputs"][name] = seed
        if node["class_type"].startswith("Save") and "filename_prefix" in node["inputs"]:
            node["inputs"]["filename_prefix"] = f"{OUTPUT_PREFIX}/{job['id']}"
    return copy.deepcopy(prompt)


class ProgressWatcher:
    """Follows ComfyUI's websocket for one job: the sampler's step and speed. Standard library websocket client: text
    frames only, the binary preview frames are skipped."""

    def __init__(self, client_id, job):
        self.client_id = client_id
        self.job = job
        self.prompt_id = None
        self.running = True
        self.sock = None
        self.last = None

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def run(self):
        try:
            url = urllib.parse.urlparse(args.comfy)
            self.sock = socket.create_connection((url.hostname, url.port), timeout=10)
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f"GET /ws?clientId={self.client_id} HTTP/1.1\r\nHost: {url.netloc}\r\n"
                               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = self.sock.recv(1024)
                if not chunk:
                    return
                header += chunk
            if b" 101 " not in header.split(b"\r\n")[0]:
                return
            buffer = header.split(b"\r\n\r\n", 1)[1]
            self.sock.settimeout(None)
            while self.running:
                frame, buffer = self.read_frame(buffer)
                if frame is None:
                    return
                opcode, payload = frame
                if opcode == 1:
                    self.handle(json.loads(payload))
                elif opcode == 8:
                    return
        except (OSError, ValueError):
            return

    def read_frame(self, buffer):
        def need(count):
            nonlocal buffer
            while len(buffer) < count:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise OSError("closed")
                buffer += chunk
        need(2)
        opcode = buffer[0] & 0x0F
        length = buffer[1] & 0x7F
        offset = 2
        if length == 126:
            need(4)
            length = struct.unpack(">H", buffer[2:4])[0]
            offset = 4
        elif length == 127:
            need(10)
            length = struct.unpack(">Q", buffer[2:10])[0]
            offset = 10
        need(offset + length)
        payload = buffer[offset:offset + length]
        return (opcode, payload), buffer[offset + length:]

    def handle(self, message):
        data = message.get("data") or {}
        if self.prompt_id and data.get("prompt_id") not in (None, self.prompt_id):
            return
        if message.get("type") == "progress":
            value, maximum = data.get("value", 0), data.get("max", 0)
            now = time.time()
            if self.last and value > self.last[0] and maximum == self.job.get("steps"):
                speed = (value - self.last[0]) / max(1e-3, now - self.last[1])
                previous = self.job.get("it_s") or speed
                self.job["it_s"] = round(0.5 * previous + 0.5 * speed, 4)
            if not self.last or value != self.last[0]:
                self.last = (value, now)
            self.job["step"], self.job["steps"] = value, maximum
        elif message.get("type") == "executing" and data.get("node"):
            self.job["node"] = data.get("display_node") or data.get("node")


# --- the web side -------------------------------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "comfyui-hive"

    def log_message(self, *_):
        pass

    def send(self, code, body, kind="application/json", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode() if kind == "application/json" else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "page.html"), "rb") as handle:
                self.send(200, handle.read(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.send(200, rig.state())
        elif url.path == "/log":
            self.send(200, tail(args.log, 64 * 1024), "text/plain; charset=utf-8")
        elif url.path.startswith("/files/"):
            self.send_output(urllib.parse.unquote(url.path[len("/files/"):]),
                             "download" in urllib.parse.parse_qs(url.query))
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD * 1.5:
            self.send(413, {"error": "too big"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send(400, {"error": "not JSON"})
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/generate":
            job, error = rig.add_job(body)
            self.send(400 if error else 200, {"error": error} if error else {"job": job["id"]})
        elif path == "/api/cancel":
            rig.cancel_job(str(body.get("job")))
            self.send(200, {})
        elif path == "/api/download":
            error = rig.start_download(str(body.get("model")))
            self.send(400 if error else 200, {"error": error})
        elif path == "/api/cancel-download":
            rig.cancel_download(str(body.get("model")))
            self.send(200, {})
        elif path == "/api/delete":
            error = rig.delete_model(str(body.get("model")))
            self.send(400 if error else 200, {"error": error})
        elif path == "/api/token":
            token = str(body.get("token") or "").strip()
            if token and not re.match(r"^hf_[A-Za-z0-9]+$", token):
                self.send(400, {"error": "A Hugging Face token starts with hf_"})
                return
            target = os.path.join(args.data, "hf_token")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(token)
            rig.token = token or os.environ.get("HF_TOKEN", "")
            self.send(200, {})
        else:
            self.send(404, {"error": "not found"})

    def send_output(self, relative, download):
        root = os.path.realpath(args.outputs)
        path = os.path.realpath(os.path.join(root, relative))
        if not path.startswith(root + os.sep) or not os.path.isfile(path):
            self.send(404, {"error": "not found"})
            return
        size = os.path.getsize(path)
        kind = {".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".flac": "audio/flac", ".mp3": "audio/mpeg",
                ".wav": "audio/wav"}.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        start, end = 0, size - 1
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
        self.send_response(206 if match else 200)
        self.send_header("Content-Type", kind)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if match:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.end_headers()
        with open(path, "rb") as handle:
            handle.seek(start)
            left = end - start + 1
            while left > 0:
                block = handle.read(min(CHUNK, left))
                if not block:
                    break
                try:
                    self.wfile.write(block)
                except OSError:
                    return
                left -= len(block)


def tail(path, length):
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, os.path.getsize(path) - length))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def main():
    global args, rig
    parser = argparse.ArgumentParser()
    for name in ("bind", "comfy", "catalog", "workflows", "models", "outputs", "inputs", "data", "state-file",
                 "page-file", "log"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    for folder in (args.models, args.outputs, args.inputs, args.data):
        os.makedirs(folder, exist_ok=True)
    rig = Rig()
    if rig.gpu:
        offered = [m["name"] for m in rig.models()]
        log(f"GPU {rig.gpu['name']}, {rig.gpu['vram_gb']} GB: {len(offered)} models fit: {', '.join(offered)}")
    else:
        log("No GPU found: no models are offered")
    for loop in (rig.download_loop, rig.job_loop, rig.stats_loop):
        threading.Thread(target=loop, daemon=True).start()
    server = http.server.ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    server.serve_forever()


rig = None

if __name__ == "__main__":
    main()

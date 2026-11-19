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
  /api/state      the rig, its models, the chats, the jobs (?chat=<id>: that chat's), what is happening now
  /api/generate   POST {model, task, prompt, chat?, image?, width?, height?, length?, seed?, loras?}: queues a job
  /api/chat-new   POST {title?}: starts a chat; /api/chat-update {chat, title?, archived?}; /api/chat-delete {chat}
  /api/chat-settings  POST {chat, settings}: what the page's composer is set to in that chat, to open it with again
  /api/chat-image     POST {chat, image}: the image attached in that chat (null: none), or {chat, job} for the one a
                      request started from, or {chat, output} for an image the rig made; GET ?chat=<id>: that image
  /api/outputs    every file in the outputs folder; /api/outputs-delete POST {paths}: deletes some
  /api/cancel     POST {job}: drops a queued job or stops the running one
  /api/download   POST {model}: downloads the model's files; /api/cancel-download and /api/delete likewise
  /api/token      POST {token}: the Hugging Face token for gated models, kept on the rig
  /api/lora-upload  POST ?name=<file>.safetensors with the file as the body: adds one of your own LoRAs
  /api/lora-delete  POST {name}: deletes one
  /files/<path>   an output, ?download=1 to save it
  /log            the end of the miner log
  /api/hello      who this rig is, for the other rigs; /api/rigs: the other rigs it found; /api/chats: its chats
  /rig/<address:port>/<any of the above>  the same on another rig, passed on to it: one page for every rig's chats

Anything that can reach the port can use it: like ComfyUI itself, it listens only on the private LAN address, and the
firewall rules of h-run.sh limit it to allow=. Standard library only, so it runs before ComfyUI's packages are installed.
"""

import argparse
import base64
import copy
import fractions
import hashlib
import http.client
import http.server
import ipaddress
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
KEEP_JOBS = 2000  # across all chats
SHOW_JOBS = 100  # of a chat, on the page
DEFAULT_CHAT = "default"  # where a request without a chat goes: the Claude Code tools, and the history from before chats
MAX_UPLOAD = 40 * 1024 * 1024
MAX_SETTINGS = 50000  # characters of a chat's settings as JSON
IMAGE_KINDS = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
MAX_LORA = 8 * 1024 ** 3
LORA_DIR = "loras"  # in the models folder, where ComfyUI looks for them
LORA_EXT = ".safetensors"
SPARE_DISK = 2 * 1024 ** 3  # left free on the data drive after a download
OUTPUT_PREFIX = "comfyui-hive"
# The nodes that take the steps. A workflow can have several (Wan 2.2 14B's high-noise and low-noise halves, LTX's two
# stages): each is a pass of the request, and counts its own steps.
SAMPLERS = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced")
# What is worked out while a request runs, and not kept with it afterwards
APP = "comfyui-hive"
ANNOUNCE = b"comfyui-hive "  # then the page's port: what a rig tells the LAN every few seconds
PEER_HEARD = 60  # seconds a rig is asked who it is after it last announced itself
PEER_KEPT = 20  # seconds a rig stays listed after it last answered
MAX_STITCH = 40  # videos in one row
RUN_FIELDS = ("est", "shown", "begun", "first", "last", "rate", "all_step", "all_steps", "pass", "passes")

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


def read_image(text):
    """An image sent as a data URL: its kind (png, jpg, webp) and bytes, or None and why not."""
    match = re.match(r"^data:image/(png|jpeg|webp);base64,(.+)$", str(text or ""), re.S)
    if not match:
        return None, None, "That isn't a PNG, JPEG or WebP image"
    try:
        data = base64.b64decode(match.group(2))
    except ValueError:
        return None, None, "The image didn't arrive whole"
    if len(data) > MAX_UPLOAD:
        return None, None, "The image is too big"
    return "jpg" if match.group(1) == "jpeg" else match.group(1), data, None


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


def rental():
    """What says someone else may have the GPU, a rental above all, or "": a GPU process that isn't ComfyUI, or a
    running Docker container (a rented one can be idle). What h-run.sh waits for before it starts, asked again before
    each request: a rental can begin while this flight sheet is on."""
    def ours(pid, server):
        # ComfyUI, or a process it started
        for _ in range(20):
            if pid == server:
                return True
            try:
                with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
                    pid = handle.read().rsplit(")", 1)[1].split()[1]
            except (OSError, IndexError):
                return False
        return False

    def lines(command):
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    # Without ComfyUI's pid its own process can't be told from another's, so the GPU's processes aren't looked at
    server = read_line(os.path.join(os.path.dirname(args.state_file), "server.pid"))
    if server:
        apps = lines(["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"])
        apps = [app for app in apps if not ours(app.split(",")[0].strip(), server)]
        if apps:
            return "the GPU is in use by " + "; ".join(apps)
    if not args.allow_docker:
        containers = lines(["docker", "ps", "--format", "{{.Names}}"])
        if containers:
            return ("Docker containers are running: " + ", ".join(containers)
                    + ". If they are safe to share with, set allow_docker=1 in the flight sheet")
    return ""


def rental_refusal():
    found = rental()
    return f"A rental may be active on this rig, so nothing was started: {found}" if found else ""


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


# --- LoRAs --------------------------------------------------------------------------------------------------------
# Your own LoRA files, uploaded on the page. They share the loras folder with the ones catalog models bring (the
# speed-up LoRAs) but are apart from the catalog's downloads: a model's Download and Delete never touch them, and
# these never list or delete a catalog file.

def lora_root():
    return os.path.join(args.models, LORA_DIR)


def lora_file_name(name):
    """A safe file name for an uploaded LoRA, or None: no folders, .safetensors only."""
    name = re.split(r"[\\/]", str(name or ""))[-1]
    name = re.sub(r"[^A-Za-z0-9._ ()+-]", "_", name).strip(" .")
    if not name.lower().endswith(LORA_EXT) or not len(LORA_EXT) < len(name) <= 200:
        return None
    return name


def looks_like_safetensors(start, length):
    """A safetensors file starts with the length of its JSON header, then the header."""
    if len(start) < 9:
        return False
    header = struct.unpack("<Q", start[:8])[0]
    return 2 <= header <= min(length - 8, 100 * 1024 ** 2) and start[8:9] == b"{"


def add_loras(prompt, after, slots, clip=None):
    """Puts the job's LoRAs into a workflow: a chain of LoraLoaderModelOnly, one per slot, after each model output
    named in `after` ([node] or [node, "low"]), and everything that took that output takes the end of the chain
    instead. So they add to whatever the workflow already applies (the speed-up LoRAs). A model marked "low" is the
    low-noise one of a pair: it gets the slot's low file when the slot has one, else the same file as the others.
    With `clip` ([node, output] of the text encoder, for a single model), each slot is a LoraLoader that applies the
    LoRA to that text encoder too, at the same strength, as SD 1.5 and SDXL LoRAs expect."""
    for index, (node_id, *low) in enumerate(after):
        source = [node_id, 0]
        clip_source = list(clip) if clip and index == 0 else None
        takers = [(node, name) for node in prompt.values() for name, value in node["inputs"].items() if value == source]
        clip_takers = [(node, name) for node in prompt.values() for name, value in node["inputs"].items()
                       if clip_source and value == clip_source]
        for number, slot in enumerate(slots, 1):
            new_id = f"lora-{number}-{index}"
            lora_name = (low and slot.get("low")) or slot["name"]
            if clip_source:
                prompt[new_id] = {"class_type": "LoraLoader",
                                  "inputs": {"lora_name": lora_name, "strength_model": slot["strength"],
                                             "strength_clip": slot["strength"], "model": source, "clip": clip_source},
                                  "_meta": {"title": f"LoRA {number}"}}
                clip_source = [new_id, 1]
            else:
                prompt[new_id] = {"class_type": "LoraLoaderModelOnly",
                                  "inputs": {"lora_name": lora_name, "strength_model": slot["strength"],
                                             "model": source},
                                  "_meta": {"title": f"LoRA {number}"}}
            source = [new_id, 0]
        for node, name in takers:
            node["inputs"][name] = source
        for node, name in clip_takers:
            node["inputs"][name] = clip_source


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
        self.rental = ""  # what says a rental may be active, looked at every few seconds for the page
        self.id = f"{random.randrange(16 ** 12):012x}"  # of this run: how a rig knows its own announcement
        self.name = args.name or socket.gethostname()
        self.heard = {}  # "address:port" -> when a rig announced itself from there
        self.peers = {}  # "address:port" -> {id, name, version, seen}: the other rigs that answered
        try:
            # An upload the miner stopped in the middle of
            for name in os.listdir(lora_root()):
                if name.endswith(".upload"):
                    os.remove(os.path.join(lora_root(), name))
        except OSError:
            pass
        self.chats = read_json(os.path.join(args.data, "chats.json"), [])
        for line in self.read_jobs():
            if line.get("state") in ("queued", "running"):
                line["state"] = "failed"
                line["error"] = "The miner stopped before this was done"
            line.setdefault("chat", DEFAULT_CHAT)
            self.jobs.append(line)
        if any(job["chat"] == DEFAULT_CHAT for job in self.jobs):
            self.default_chat()

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

    # LoRAs ---

    def catalog_loras(self):
        return {entry["name"] for model in self.catalog["models"] for entry in model["files"].values()
                if entry["dir"] == LORA_DIR}

    def loras(self):
        """Your LoRAs: every .safetensors under the loras folder that no catalog model brought, by the name ComfyUI
        gives it (with its folder, for one copied into a subfolder by hand)."""
        root, skip, found = lora_root(), self.catalog_loras(), []
        for folder, _, names in os.walk(root, followlinks=True):
            for name in names:
                relative = os.path.relpath(os.path.join(folder, name), root)
                if not name.lower().endswith(LORA_EXT) or relative in skip:
                    continue
                try:
                    found.append({"name": relative, "size": os.path.getsize(os.path.join(folder, name))})
                except OSError:
                    pass
        return sorted(found, key=lambda entry: entry["name"].lower())

    def save_lora(self, asked_name, stream, length):
        """Writes an uploaded LoRA into the loras folder. Returns its name there, or None and why not."""
        name = lora_file_name(asked_name)
        if name is None:
            return None, f"A LoRA is a {LORA_EXT} file"
        if length <= 0:
            return None, "The file is empty"
        if length > MAX_LORA:
            return None, f"A LoRA can be {MAX_LORA / 1024 ** 3:.0f} GB at most"
        if length + SPARE_DISK > disk_free():
            return None, f"Not enough free space: {disk_free() / 1024 ** 3:.1f} GB is free"
        path = os.path.join(lora_root(), name)
        if name in self.catalog_loras() or os.path.exists(path):
            return None, f"{name} is already on this rig: delete it first to replace it"
        os.makedirs(lora_root(), exist_ok=True)
        temp = path + ".upload"
        try:
            handle = open(temp, "xb")
        except FileExistsError:
            return None, f"{name} is being uploaded already"
        try:
            with handle:
                left = length
                while left:
                    block = stream.read(min(CHUNK, left))
                    if not block:
                        raise OSError("the upload stopped before the end")
                    if left == length and not looks_like_safetensors(block, length):
                        raise OSError(f"it isn't a {LORA_EXT} file inside")
                    handle.write(block)
                    left -= len(block)
            os.replace(temp, path)
        except OSError as error:
            try:
                os.remove(temp)
            except OSError:
                pass
            return None, f"{name}: {error}"
        log(f"LoRA {name} uploaded: {length / 1024 ** 2:.0f} MB")
        return name, None

    def delete_lora(self, name):
        if name not in {entry["name"] for entry in self.loras()}:
            return "No such LoRA on this rig"
        with lock:
            used = {slot.get(key) for job in self.jobs if job["state"] in ("queued", "running")
                    for slot in job.get("loras", []) for key in ("name", "low")}
        if name in used:
            return "A request is using it"
        try:
            os.remove(os.path.join(lora_root(), name))
        except OSError as error:
            return f"{name}: {error}"
        log(f"LoRA {name} deleted")
        return None

    def read_loras(self, item, asked):
        """The LoRA slots of a request, checked against the task's "loras" input: [{name, low?, strength}]. A slot
        without a file isn't used."""
        if not isinstance(asked, list):
            return None, "loras must be a list"
        have = {entry["name"] for entry in self.loras()}
        limits = item["strength"]
        paired = any(len(target) > 1 for target in item["after"])
        slots = []
        for slot in asked:
            if not isinstance(slot, dict) or not slot.get("name"):
                continue
            entry = {"name": str(slot["name"])}
            if paired and slot.get("low"):
                entry["low"] = str(slot["low"])
            for name in (entry["name"], entry.get("low")):
                if name is not None and name not in have:
                    return None, f"There is no LoRA {name} on this rig"
            try:
                strength = slot.get("strength")
                entry["strength"] = limits["default"] if strength in ("", None) else float(strength)
            except (TypeError, ValueError):
                return None, "A LoRA's strength must be a number"
            if not limits["min"] <= entry["strength"] <= limits["max"]:
                return None, f"A LoRA's strength must be between {limits['min']} and {limits['max']}"
            slots.append(entry)
        if len(slots) > item["slots"]:
            return None, f"{item['slots']} LoRAs at most"
        return slots, None

    # chats ---
    # A chat is a name over some of the requests: each job says which chat it is in.

    def find_chat(self, chat_id):
        return next((chat for chat in self.chats if chat["id"] == chat_id), None)

    def save_chats(self):
        write_json(os.path.join(args.data, "chats.json"), self.chats)

    def new_chat(self, title="", chat_id=None):
        chat = {"id": chat_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{random.randrange(16 ** 4):04x}",
                "title": str(title or "").strip()[:80], "created": time.time(), "archived": False}
        with lock:
            self.chats.append(chat)
            self.save_chats()
        return chat

    def default_chat(self):
        with lock:
            return self.find_chat(DEFAULT_CHAT) or self.new_chat("General", DEFAULT_CHAT)

    def update_chat(self, chat_id, title=None, archived=None):
        with lock:
            chat = self.find_chat(chat_id)
            if chat is None:
                return "No such chat"
            if title is not None:
                chat["title"] = str(title).strip()[:80]
            if archived is not None:
                chat["archived"] = bool(archived)
            self.save_chats()
        return None

    def delete_chat(self, chat_id):
        """Deletes a chat with its requests, and the files they made and started from."""
        with lock:
            chat = self.find_chat(chat_id)
            if chat is None:
                return "No such chat"
            mine = [job for job in self.jobs if job["chat"] == chat_id]
            if any(job["state"] in ("queued", "running") for job in mine):
                return "A request is waiting or running in it: cancel that first"
            self.remove_outputs([path for job in mine for path in job["outputs"]])
            self.drop_image(chat)
            for job in mine:
                if job.get("image"):
                    try:
                        os.remove(os.path.join(args.inputs, os.path.basename(job["image"])))
                    except OSError:
                        pass
            self.jobs = [job for job in self.jobs if job["chat"] != chat_id]
            self.chats.remove(chat)
            self.save_chats()
            self.save_jobs()
        log(f"Chat {chat['title'] or chat_id} deleted with {len(mine)} requests")
        return None

    def set_settings(self, chat_id, settings):
        """Keeps what the page's composer is set to in a chat: the model, the task, the numbers, the LoRAs."""
        if not isinstance(settings, dict) or len(json.dumps(settings)) > MAX_SETTINGS:
            return "Those aren't a chat's settings"
        with lock:
            chat = self.find_chat(chat_id)
            if chat is None:
                return "No such chat"
            chat["settings"] = settings
            self.save_chats()
        return None

    # The image attached in a chat is kept in the inputs folder, apart from the copies its requests started from: it
    # is there again when the chat is opened, on any PC or phone.

    def image_path(self, chat):
        return os.path.join(args.inputs, chat["image"]["name"]) if chat.get("image") else None

    def drop_image(self, chat):
        if chat.get("image"):
            try:
                os.remove(self.image_path(chat))
            except OSError:
                pass
            chat.pop("image")

    def keep_image(self, chat, kind, data):
        """Makes an image the chat's attached one. Returns what tells it from the one before."""
        with lock:
            old = self.image_path(chat)
            name = f"chat-{chat['id']}.{kind}"
            try:
                if old and chat["image"]["name"] == name and os.path.getsize(old) == len(data):
                    with open(old, "rb") as handle:
                        if handle.read() == data:
                            return chat["image"]["stamp"]
            except OSError:
                pass
            self.drop_image(chat)
            with open(os.path.join(args.inputs, name), "wb") as handle:
                handle.write(data)
            chat["image"] = {"name": name, "stamp": time.time()}
            self.save_chats()
            return chat["image"]["stamp"]

    def stored_image(self, job_id, output):
        """An image already on the rig, to attach again: the one a request started from, or one that was made. Its
        kind and bytes, or None and why not."""
        if job_id:
            with lock:
                job = next((job for job in self.jobs if job["id"] == job_id), None)
            path = os.path.join(args.inputs, os.path.basename(job["image"])) if job and job.get("image") else None
        else:
            root = os.path.realpath(args.outputs)
            path = os.path.realpath(os.path.join(root, str(output)))
            if not path.startswith(root + os.sep):
                path = None
        kind = os.path.splitext(path or "")[1].lower().lstrip(".").replace("jpeg", "jpg")
        if kind not in IMAGE_KINDS:
            return None, None, "That isn't an image to start from"
        try:
            if os.path.getsize(path) > MAX_UPLOAD:
                return None, None, "The image is too big"
            with open(path, "rb") as handle:
                return kind, handle.read(), None
        except OSError:
            return None, None, "That image is no longer on the rig"

    def set_image(self, chat_id, image, job_id=None, output=None):
        """The page's attach and Remove, and attaching an image the rig has. Returns the image's stamp (None: no
        image now), or None and why not."""
        kind = data = None
        if job_id or output:
            kind, data, error = self.stored_image(job_id, output)
            if error:
                return None, error
        elif image is not None:
            kind, data, error = read_image(image)
            if error:
                return None, error
        with lock:
            chat = self.find_chat(chat_id)
            if chat is None:
                return None, "No such chat"
            if data is None:
                self.drop_image(chat)
                self.save_chats()
                return None, None
            return self.keep_image(chat, kind, data), None

    def chat_list(self):
        """The chats, the one last used first, each with how many requests it has and whether one is under way:
        how far the running one is and how long it has left, for the bar in the list of chats."""
        with lock:
            out, now = [], time.time()
            for chat in self.chats:
                mine = [job for job in self.jobs if job["chat"] == chat["id"]]
                running = next((j for j in mine if j["state"] == "running"), None)
                fraction, left, rough = job_progress(running, now) if running and running.get("begun") else (None, None, True)
                out.append(dict(chat, jobs=len(mine), busy=any(j["state"] in ("queued", "running") for j in mine),
                                running=bool(running), progress=fraction,
                                eta=None if left is None or rough else round(left),
                                last=max([chat["created"]] + [j["created"] for j in mine])))
        return sorted(out, key=lambda chat: -chat["last"])

    # other rigs ---

    def hello(self):
        return {"app": APP, "id": self.id, "name": self.name, "version": args.version}

    def rigs(self):
        with lock:
            found = [{"id": peer, "name": info["name"], "version": info["version"]} for peer, info in self.peers.items()]
        return sorted(found, key=lambda peer: (peer["name"], peer["id"]))

    def listen_loop(self):
        """Hears the other rigs of the LAN announce themselves. Only an address comes of it: peers_loop asks who it is."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Not the LAN address: Linux gives a broadcast only to a socket bound to every address
            sock.bind(("", args.port))
        except OSError as error:
            log(f"Other rigs are not heard: UDP port {args.port} can't be listened on ({error})")
            return
        while True:
            try:
                data, sender = sock.recvfrom(256)
            except OSError:
                time.sleep(1)
                continue
            port = data[len(ANNOUNCE):]
            if not data.startswith(ANNOUNCE) or not port.isdigit() or not 0 < int(port) < 65536:
                continue
            try:
                private = ipaddress.ip_address(sender[0]).is_private
            except ValueError:
                continue
            peer = f"{sender[0]}:{int(port)}"
            with lock:
                if private and (len(self.heard) < 200 or peer in self.heard):
                    self.heard[peer] = time.time()

    def peers_loop(self):
        """Announces this rig to the LAN, and asks each rig heard there or named in peers= who it is."""
        named = [peer if ":" in peer else f"{peer}:{args.port}" for peer in args.peers.split(",") if peer]
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sender.bind((args.bind, 0))
        except OSError:
            pass
        while True:
            try:
                sender.sendto(ANNOUNCE + str(args.port).encode(), ("255.255.255.255", args.port))
            except OSError:
                pass
            now = time.time()
            with lock:
                self.heard = {peer: at for peer, at in self.heard.items() if now - at < PEER_HEARD}
                asked = sorted(set(named) | set(self.heard))
                found = {peer: info for peer, info in self.peers.items() if now - info["seen"] < PEER_KEPT}
            for peer in asked:
                try:
                    with urllib.request.urlopen(f"http://{peer}/api/hello", timeout=3) as response:
                        answer = json.loads(response.read(4096))
                except (OSError, ValueError):
                    continue
                if not isinstance(answer, dict) or answer.get("app") != APP or answer.get("id") == self.id:
                    continue
                # One rig reached at two addresses is listed once
                if any(info["id"] == answer.get("id") for other, info in found.items() if other != peer):
                    continue
                found[peer] = {"id": answer.get("id"), "name": str(answer.get("name") or peer)[:60],
                               "version": str(answer.get("version") or "")[:20], "seen": time.time()}
            with lock:
                self.peers = found
            time.sleep(5)

    # outputs ---

    def outputs(self):
        """Every file in the outputs folder, newest first, with the request that made it when the history has it."""
        root = os.path.realpath(args.outputs)
        with lock:
            makers = {path: job for job in self.jobs for path in job["outputs"]}
        found = []
        for folder, _, names in os.walk(root):
            for name in names:
                full = os.path.join(folder, name)
                relative = os.path.relpath(full, root).replace(os.sep, "/")
                try:
                    entry = {"path": relative, "size": os.path.getsize(full), "modified": os.path.getmtime(full)}
                except OSError:
                    continue
                job = makers.get(relative)
                if job:
                    entry.update(job=job["id"], chat=job["chat"], prompt=job["prompt"], model=job["model_name"],
                                 task=job["task"])
                found.append(entry)
        return sorted(found, key=lambda entry: -entry["modified"])

    def remove_outputs(self, paths):
        """Deletes files of the outputs folder, and takes them off the requests that made them. Returns how many."""
        root = os.path.realpath(args.outputs)
        gone = set()
        for relative in paths:
            full = os.path.realpath(os.path.join(root, str(relative)))
            if not full.startswith(root + os.sep) or not os.path.isfile(full):
                continue
            try:
                os.remove(full)
                gone.add(os.path.relpath(full, root).replace(os.sep, "/"))
            except OSError:
                pass
        with lock:
            for job in self.jobs:
                kept = [path for path in job["outputs"] if path not in gone]
                if len(kept) != len(job["outputs"]):
                    job["removed"] = job.get("removed", 0) + len(job["outputs"]) - len(kept)
                    job["outputs"] = kept
            if gone:
                self.save_jobs()
        return len(gone)

    def delete_outputs(self, paths):
        if not isinstance(paths, list):
            return None, "paths must be a list"
        with lock:
            running = {path for job in self.jobs if job["state"] == "running" for path in job["outputs"]}
        count = self.remove_outputs([path for path in paths if path not in running])
        log(f"{count} output files deleted")
        return count, None

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

    def add_job(self, request, via=""):
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
        refusal = rental_refusal()
        if refusal:
            return None, refusal
        spec = model["tasks"][task]
        chat = self.find_chat(str(request["chat"])) if request.get("chat") else self.default_chat()
        if chat is None:
            return None, "That chat was deleted: pick or start another"
        job = {"id": f"{time.strftime('%Y%m%d-%H%M%S')}-{random.randrange(16 ** 4):04x}", "model": model["id"],
               "chat": chat["id"],
               "model_name": model["name"], "variant": variant["label"], "task": task, "prompt": prompt,
               "state": "queued", "created": time.time(), "outputs": [], "error": "", "values": {}}
        if via:
            job["via"] = via  # the rig whose page it was sent from
        for item in spec["inputs"]:
            name = item["name"]
            if name in ("prompt", "image") or name not in request or request[name] in ("", None):
                continue
            if item["kind"] == "loras":
                slots, error = self.read_loras(item, request[name])
                if error:
                    return None, error
                if slots:
                    job["loras"] = slots
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
            # The request's own copy: the chat's image can change while this waits in the queue
            if request.get("image"):
                kind, data, error = read_image(request["image"])
                if error:
                    return None, error
                job["image"] = f"{job['id']}.{kind}"
                with open(os.path.join(args.inputs, job["image"]), "wb") as handle:
                    handle.write(data)
                self.keep_image(chat, kind, data)
            else:
                # Sent without one: the image attached in the chat before
                with lock:
                    kept = self.image_path(chat)
                    if not kept or not os.path.isfile(kept):
                        return None, "This needs an image: attach one"
                    job["image"] = job["id"] + os.path.splitext(kept)[1]
                    shutil.copyfile(kept, os.path.join(args.inputs, job["image"]))
            if request.get("continues"):
                # It starts from the last frame of that request's video: the two belong in a row
                with lock:
                    before = next((j for j in self.jobs if j["id"] == str(request["continues"])), None)
                if before and before["chat"] == chat["id"]:
                    job["continues"] = before["id"]
                    job["stitch"] = bool(request.get("stitch"))
        if request.get("seed") not in (None, ""):
            try:
                job["seed"] = int(request["seed"])
            except (TypeError, ValueError):
                return None, "seed must be a number"
        with lock:
            if self.find_chat(chat["id"]) is None:
                return None, "That chat was deleted: pick or start another"
            if not chat["title"]:
                # A chat is named after its first request, until it is renamed
                chat["title"] = prompt[:60]
            chat["archived"] = False
            self.save_chats()
            self.jobs.append(job)
            self.settings ={"model": model["id"], "task": task}
            write_json(os.path.join(args.data, "settings.json"), self.settings)
            self.save_jobs()
            wake_jobs.notify_all()
        log(f"Job {job['id']}: {model['name']} {task}: {prompt[:120]}")
        return job, None

    def stitch(self, job):
        """Makes one video of a request's and those it continues, in a row, beside the request's own. Each part is
        taken from the request that made it, never from an earlier stitched one, so nothing is encoded twice over."""
        with lock:
            parts, link = [], job
            while link and len(parts) < MAX_STITCH:
                video = next((path for path in link["outputs"] if is_video(path) and path != link.get("stitched")), None)
                if video is None:
                    break  # deleted since: the row starts after it
                parts.insert(0, video)
                link = next((j for j in self.jobs if j["id"] == link.get("continues")), None)
        if len(parts) < 2:
            job["stitch_error"] = "Not stitched: the video this continues is no longer on the rig"
            return
        name = os.path.splitext(parts[-1])[0] + "-stitched.mp4"
        try:
            stitch_videos([os.path.join(args.outputs, path) for path in parts], os.path.join(args.outputs, name))
        except Exception as error:  # noqa: BLE001 - the request's own video is there all the same
            job["stitch_error"] = f"Not stitched: {error}"
            log(f"Job {job['id']}: not stitched: {error}")
            return
        job["stitched"], job["parts"] = name, len(parts)
        job["outputs"].append(name)
        log(f"Job {job['id']}: {len(parts)} videos stitched into {name}")

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
            for name in RUN_FIELDS:
                job.pop(name, None)
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
        # Asked when the request came in too; one that waited in the queue may start much later
        refusal = rental_refusal()
        if refusal:
            raise RuntimeError(refusal)
        prompt = build_prompt(model, variant, job)
        samplers = {node_id for node_id, node in prompt.items() if node["class_type"] in SAMPLERS}
        job["passes"] = len(samplers)
        # Loading takes far longer when the model before was another one
        job["warm"] = self.last_model == job["model"]
        with lock:
            job["est"] = self.estimate(job)
        if self.last_model and self.last_model != job["model"]:
            # Another model: let go of the last one's memory first rather than squeezing both
            comfy_post("/free", {"unload_models": True, "free_memory": True})
        self.last_model = job["model"]
        client_id = hashlib.sha1(job["id"].encode()).hexdigest()
        watcher = ProgressWatcher(client_id, job, samplers)
        watcher.start()
        job["begun"] = time.time()
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
        if job.get("stitch"):
            self.stitch(job)
        if job.get("first"):
            # How long each part took, for the estimate of the next request like this one. The time per step is over
            # all passes, so what goes on between them (the other half's model loading) is in it.
            steps = job.get("all_step") or 0
            job["took"] = {"load": round(job["first"] - job["begun"], 2), "steps": steps,
                           "rate": round((job["last"] - job["first"]) / (steps - 1), 4) if steps > 1 else None,
                           "tail": round(time.time() - job["last"], 2)}

    def estimate(self, job):
        """What the parts of a request will take, from the last ones like it: the time to the first step (load) from
        one of the same model and task, that started as warm or cold as this one if there is one; the steps, the time of each (rate)
        and the time after the last (tail) from one with the same settings too. Only what is known is in it."""
        est, other = {}, None
        for old in reversed(self.jobs):
            took = old.get("took")
            if not took or old["model"] != job["model"] or old["task"] != job["task"]:
                continue
            if "load" not in est and old.get("warm") == job["warm"]:
                est["load"] = took["load"]
            elif other is None:
                other = took["load"]
            if "tail" not in est and old["values"] == job["values"] \
                    and len(old.get("loras") or []) == len(job.get("loras") or []):
                est.update(tail=took["tail"], rate=took["rate"], steps=took["steps"])
            if len(est) == 4:
                break
        if "load" not in est and other is not None:
            # Better than no estimate until the first step: the load of one that started the other way
            est["load"] = other
        return est

    def expected(self, job, warm):
        """The seconds a request not started yet will take, or None when no request like it has been timed."""
        est = self.estimate(dict(job, warm=warm))
        if len(est) < 4:
            return None
        return est["load"] + max(0, est["steps"] - 1) * (est["rate"] or 0) + est["tail"]

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
                    self.rental = rental()
            except OSError:
                pass
            time.sleep(2)

    def state(self, chat_id=None):
        """For the page: a chat's requests. Without a chat, the last requests of all of them (the Claude Code tools)."""
        with lock:
            jobs = [j for j in self.jobs if j["chat"] == chat_id][-SHOW_JOBS:] if chat_id else self.jobs[-60:]
            jobs = [{k: v for k, v in j.items() if k not in ("cancel", "est", "shown", "took")} for j in jobs]
            shown = {job["id"]: job for job in jobs}
            now = time.time()
            running = next((j for j in self.jobs if j["state"] == "running"), None)
            # How long until each waiting request starts: what is left of the running one, and the ones before it
            wait, ahead, before = 0, 0, self.last_model
            if running:
                fraction, left, rough = job_progress(running, now) if running.get("begun") else (None, None, True)
                wait, ahead, before = None if rough else left, 1, running["model"]
                if running["id"] in shown and running.get("begun"):
                    shown[running["id"]].update(progress=fraction, eta=None if left is None else round(left, 1),
                                                eta_rough=rough, elapsed=round(now - running["begun"], 1))
            for job in self.jobs:
                if job["state"] != "queued":
                    continue
                if job["id"] in shown:
                    shown[job["id"]].update(ahead=ahead, wait=None if wait is None else round(wait))
                took = self.expected(job, before == job["model"])
                wait = None if wait is None or took is None else wait + took
                ahead, before = ahead + 1, job["model"]
        return {
            "rental": self.rental, "name": self.name,
            "chat": chat_id, "chats": self.chat_list(),
            "version": args.version, "state": read_line(args.state_file) or "stopped",
            "comfy_url": args.comfy, "gpu": self.gpu, "ram_gb": self.ram,
            "disk_free": disk_free(), "models": self.models(), "jobs": jobs,
            "settings": self.settings, "has_token": bool(self.token),
            "loras": self.loras(), "lora_max": MAX_LORA,
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
        elif item["kind"] == "loras":
            add_loras(prompt, item["after"], job.get("loras") or [], item.get("clip"))
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


def is_video(path):
    return path.lower().endswith((".mp4", ".webm"))


def stitch_videos(sources, target):
    """Writes the videos one after another into one mp4. Each but the first starts from the frame the one before it
    ended on, so that frame is left out once, with the sound of its moment. They are decoded and encoded again
    (H.264, close to lossless): joining them as they are can't leave a frame out.

    With PyAV, which ComfyUI needs and has installed for its own saving of videos; this page runs in the same Python."""
    try:
        import av
        import numpy
    except ImportError as error:
        raise RuntimeError("ComfyUI's packages aren't installed yet") from error
    clips = [av.open(source) for source in sources]
    partial = target + ".part"
    try:
        first = clips[0].streams.video[0]
        rate = first.average_rate
        width, height = first.codec_context.width, first.codec_context.height
        for clip in clips[1:]:
            context = clip.streams.video[0].codec_context
            if (context.width, context.height) != (width, height):
                raise RuntimeError(f"the videos differ in size ({width} x {height} and {context.width} x {context.height})")
        sound = next((clip.streams.audio[0] for clip in clips if clip.streams.audio), None)
        with av.open(partial, "w", format="mp4") as out:
            video = out.add_stream("libx264", rate=rate, options={"crf": "14", "preset": "medium"})
            video.width, video.height, video.pix_fmt = width, height, "yuv420p"
            audio, channels, layout, hertz = None, 0, "", 0
            if sound is not None:
                channels = 1 if sound.codec_context.layout.name == "mono" else 2
                layout, hertz = "stereo" if channels == 2 else "mono", sound.codec_context.sample_rate
                audio = out.add_stream("aac", rate=hertz, layout=layout)
            frames, samples = 0, []
            for index, clip in enumerate(clips):
                began = frames
                for count, frame in enumerate(clip.decode(clip.streams.video[0])):
                    if index and count == 0:
                        continue
                    frame = frame.reformat(width, height, "yuv420p")
                    frame.pts, frame.time_base = frames, 1 / rate
                    frames += 1
                    for packet in video.encode(frame):
                        out.mux(packet)
                if audio is None:
                    continue
                # The clip's sound, cut or filled with silence to the length of its frames, so the next one starts
                # with its picture
                heard = numpy.zeros((channels, 0), dtype="float32")
                if clip.streams.audio:
                    clip.seek(0)
                    resampler = av.AudioResampler(format="fltp", layout=layout, rate=hertz)
                    pieces = [piece.to_ndarray() for frame in clip.decode(clip.streams.audio[0])
                              for piece in resampler.resample(frame)]
                    pieces += [piece.to_ndarray() for piece in resampler.resample(None)]
                    if pieces:
                        heard = numpy.concatenate(pieces, axis=1)
                    if index:
                        heard = heard[:, round(hertz / rate):]
                wanted = round((frames - began) * hertz / rate)
                heard = heard[:, :wanted]
                samples.append(numpy.pad(heard, ((0, 0), (0, wanted - heard.shape[1]))))
            for packet in video.encode():
                out.mux(packet)
            if audio is not None:
                heard = numpy.ascontiguousarray(numpy.concatenate(samples, axis=1), dtype="float32")
                size = audio.codec_context.frame_size or 1024
                for start in range(0, heard.shape[1], size):
                    frame = av.AudioFrame.from_ndarray(numpy.ascontiguousarray(heard[:, start:start + size]),
                                                       format="fltp", layout=layout)
                    frame.sample_rate, frame.pts, frame.time_base = hertz, start, fractions.Fraction(1, hertz)
                    for packet in audio.encode(frame):
                        out.mux(packet)
                for packet in audio.encode():
                    out.mux(packet)
        os.replace(partial, target)
    finally:
        for clip in clips:
            clip.close()
        if os.path.exists(partial):
            os.remove(partial)


def job_progress(job, now):
    """How far a running request is as a whole, 0 to 1, the seconds left (each None when it can't be told yet), and
    whether those seconds are only the steps', the end's being unknown.

    The time left is what is left of loading, the steps left of all passes at the pace of this request (of the last
    one like it before the second step), and what came after the last step in the last one like it (decoding,
    saving). How far it is, is the time gone over the time gone and left: so the bar fills once, and is full at the
    end. It never goes back when the estimate grows, and waits just short of full when the end comes later than
    estimated."""
    begun = job.get("begun")
    if not begun:
        return None, None, True
    est = job.get("est") or {}
    elapsed = now - begun
    done, total = job.get("all_step") or 0, job.get("all_steps") or est.get("steps") or 0
    rate = job.get("rate") or est.get("rate")
    tail = est.get("tail") or 0
    left = None
    if not done:
        if total and rate is not None and est.get("load") is not None:
            left = max(0, est["load"] - elapsed) + (total - 1) * rate + tail
    elif rate is not None:
        since = now - job["last"]
        left = max(0, (total - done) * rate - since) + tail if done < total else max(0, tail - since)
    rough = est.get("tail") is None
    if done and total and (left is None or rough):
        # The first request of its kind: how long the end takes isn't known, so the steps fill most of the bar
        fraction = 0.9 * min(1, (done + (min(1, (now - job["last"]) / rate) if rate and done < total else 0)) / total)
    elif left is not None:
        fraction = elapsed / (elapsed + left) if elapsed + left > 0 else 0
    else:
        return None, None, rough
    job["shown"] = round(min(0.99, max(fraction, job.get("shown", 0))), 4)
    return job["shown"], left, rough


class ProgressWatcher:
    """Follows ComfyUI's websocket for one job: each sampler's step, and the pace over all of them. Standard library
    websocket client: text frames only, the binary preview frames are skipped."""

    def __init__(self, client_id, job, samplers):
        self.client_id = client_id
        self.job = job
        self.samplers = samplers
        self.seen = {}  # sampler node -> (step, steps)
        self.timed = 0  # seconds between steps of the same pass, and how many steps those were
        self.counted = 0
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
            value, maximum, node = data.get("value", 0), data.get("max", 0), data.get("node")
            if self.samplers and node not in self.samplers:
                # Another node counting its own work (a decode in tiles): part of what comes after the steps
                return
            now = time.time()
            job, before = self.job, self.seen.get(node)
            if before and value > before[0]:
                self.timed += now - self.last
                self.counted += value - before[0]
                job["rate"] = round(self.timed / self.counted, 4)
                job["it_s"] = round(self.counted / max(1e-3, self.timed), 4)
            if not before or value != before[0]:
                self.last = now
                if value:
                    job.setdefault("first", now)
                    job["last"] = now
            self.seen[node] = (value, maximum)
            job["step"], job["steps"] = value, maximum
            # Over all passes: one not reached yet counts as many steps as those so far do
            passes = max(job.get("passes") or 0, len(self.seen))
            steps = sum(most for _, most in self.seen.values())
            job["pass"], job["passes"] = len(self.seen), passes
            job["all_step"] = sum(step for step, _ in self.seen.values())
            job["all_steps"] = round(steps * passes / len(self.seen))
        elif message.get("type") == "executing" and data.get("node"):
            self.job["node"] = data.get("display_node") or data.get("node")


# --- the web side -------------------------------------------------------------------------------------------------

class Limited:
    """A request's body as a file that ends where the body does."""

    def __init__(self, stream, length):
        self.stream, self.left = stream, length

    def read(self, size=-1):
        size = self.left if size is None or size < 0 else min(size, self.left)
        data = self.stream.read(size) if size else b""
        self.left -= len(data)
        return data


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

    def forward(self):
        """A request for /rig/<address:port>/<path>: passed on to that rig, and its answer back, both as they come.

        Only to a rig that answered /api/hello as one, so this is no way to reach anything else on the LAN."""
        parts = self.path.split("/", 3)
        peer = urllib.parse.unquote(parts[2]) if len(parts) == 4 else ""
        with lock:
            known = rig.peers.get(peer)
        if not known or parts[3].startswith("rig/"):
            self.close_connection = True
            self.send(404, {"error": "That rig isn't reachable from this one any more"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        headers = {name: self.headers[name] for name in ("Content-Type", "Range") if self.headers.get(name)}
        headers["X-Hive-From"] = urllib.parse.quote(rig.name)
        if self.command == "POST":
            headers["Content-Length"] = str(length)
        host, port = peer.rsplit(":", 1)
        link = http.client.HTTPConnection(host, int(port), timeout=120)
        try:
            link.request(self.command, "/" + parts[3], body=Limited(self.rfile, length) if length else None,
                         headers=headers)
            answer = link.getresponse()
        except (OSError, http.client.HTTPException):
            link.close()
            self.close_connection = True
            self.send(502, {"error": f"{known['name']} doesn't answer"})
            return
        self.send_response(answer.status)
        for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Content-Disposition",
                     "Cache-Control"):
            if answer.getheader(name):
                self.send_header(name, answer.getheader(name))
        self.end_headers()
        try:
            while True:
                block = answer.read(256 * 1024)
                if not block:
                    break
                self.wfile.write(block)
        except (OSError, http.client.HTTPException):
            pass
        link.close()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/rig/"):
            self.forward()
        elif url.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "page.html"), "rb") as handle:
                self.send(200, handle.read(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            self.send(200, rig.state(urllib.parse.parse_qs(url.query).get("chat", [None])[0]))
        elif url.path == "/api/hello":
            self.send(200, rig.hello())
        elif url.path == "/api/rigs":
            self.send(200, {"name": rig.name, "rigs": rig.rigs()})
        elif url.path == "/api/chats":
            # Without what each chat's composer is set to: this is asked often, for the list of every rig's chats
            self.send(200, {"name": rig.name,
                            "chats": [{k: v for k, v in chat.items() if k != "settings"} for chat in rig.chat_list()]})
        elif url.path == "/api/outputs":
            self.send(200, {"outputs": rig.outputs()})
        elif url.path == "/api/chat-image":
            chat = rig.find_chat(urllib.parse.parse_qs(url.query).get("chat", [""])[0])
            path = rig.image_path(chat) if chat else None
            try:
                with open(path, "rb") as handle:
                    self.send(200, handle.read(), IMAGE_KINDS[path.rsplit(".", 1)[1]])
            except (OSError, TypeError):
                self.send(404, {"error": "not found"})
        elif url.path == "/log":
            self.send(200, tail(args.log, 64 * 1024), "text/plain; charset=utf-8")
        elif url.path.startswith("/files/"):
            self.send_output(urllib.parse.unquote(url.path[len("/files/"):]),
                             "download" in urllib.parse.parse_qs(url.query))
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/rig/"):
            self.forward()
            return
        if url.path == "/api/lora-upload":
            # The file itself is the body, written to the drive as it comes: a LoRA is far too big to hold as JSON
            name, error = rig.save_lora(urllib.parse.parse_qs(url.query).get("name", [""])[0], self.rfile, length)
            self.close_connection = True
            self.send(400 if error else 200, {"error": error} if error else {"name": name})
            return
        if length > MAX_UPLOAD * 1.5:
            self.send(413, {"error": "too big"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send(400, {"error": "not JSON"})
            return
        path = url.path
        if path == "/api/generate":
            job, error = rig.add_job(body, urllib.parse.unquote(self.headers.get("X-Hive-From") or "")[:60])
            self.send(400 if error else 200, {"error": error} if error else {"job": job["id"]})
        elif path == "/api/chat-new":
            self.send(200, {"chat": rig.new_chat(body.get("title"))["id"]})
        elif path == "/api/chat-update":
            error = rig.update_chat(str(body.get("chat")), body.get("title"), body.get("archived"))
            self.send(400 if error else 200, {"error": error})
        elif path == "/api/chat-delete":
            error = rig.delete_chat(str(body.get("chat")))
            self.send(400 if error else 200, {"error": error})
        elif path == "/api/chat-settings":
            error = rig.set_settings(str(body.get("chat")), body.get("settings"))
            self.send(400 if error else 200, {"error": error})
        elif path == "/api/chat-image":
            stamp, error = rig.set_image(str(body.get("chat")), body.get("image"), body.get("job"), body.get("output"))
            self.send(400 if error else 200, {"error": error} if error else {"stamp": stamp})
        elif path == "/api/outputs-delete":
            count, error = rig.delete_outputs(body.get("paths"))
            self.send(400 if error else 200, {"error": error} if error else {"deleted": count})
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
        elif path == "/api/lora-delete":
            error = rig.delete_lora(str(body.get("name")))
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
    parser.add_argument("--allow-docker", type=int, default=0)
    parser.add_argument("--version", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--peers", default="")
    args = parser.parse_args()
    for folder in (args.models, args.outputs, args.inputs, args.data):
        os.makedirs(folder, exist_ok=True)
    rig = Rig()
    if rig.gpu:
        offered = [m["name"] for m in rig.models()]
        log(f"GPU {rig.gpu['name']}, {rig.gpu['vram_gb']} GB: {len(offered)} models fit: {', '.join(offered)}")
    else:
        log("No GPU found: no models are offered")
    for loop in (rig.download_loop, rig.job_loop, rig.stats_loop, rig.listen_loop, rig.peers_loop):
        threading.Thread(target=loop, daemon=True).start()
    server = http.server.ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    server.serve_forever()


rig = None

if __name__ == "__main__":
    main()

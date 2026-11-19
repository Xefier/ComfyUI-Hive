#!/usr/bin/env python3
"""Tries every workflow of comfyui-hive/catalog.json, in every variant, on a running ComfyUI: does it take it?

  python tools/check.py --comfy http://127.0.0.1:8188 --models <models folder of that ComfyUI>

ComfyUI checks a workflow when it is sent (every node exists, every input is there and of the right kind, every file
name is one it has), so this catches a converter mistake, a renamed node or input, and a file the catalog doesn't
download. It makes an empty stand-in for each model file that is missing, so no model has to be downloaded; a workflow
that passes is then stopped at once, since its empty files can't load. It builds the workflows with page.py's own code.
A task that takes the user's LoRAs is sent twice: without any, and with every slot filled (the first with a high and
low pair), using empty stand-ins for those too.
"""

import argparse
import json
import os
import sys
import time
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "comfyui-hive"))
import page  # noqa: E402

# Stand-ins for a user's LoRAs, for the tasks that take them
LORAS = ["check-lora-high.safetensors", "check-lora-low.safetensors"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--inputs", help="ComfyUI's input folder, for the test image of image tasks")
    options = parser.parse_args()
    page.args = argparse.Namespace(comfy=options.comfy.rstrip("/"), models=options.models,
                                   workflows=os.path.join(ROOT, "comfyui-hive", "workflows"))
    with open(os.path.join(ROOT, "comfyui-hive", "catalog.json"), encoding="utf-8") as handle:
        catalog = json.load(handle)

    made = []
    stand_ins = [entry for model in catalog["models"] for entry in model["files"].values()]
    stand_ins += [{"dir": page.LORA_DIR, "name": name} for name in LORAS]
    for entry in stand_ins:
        path = page.file_path(entry)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").close()
            made.append(path)
    if options.inputs:
        # A 1x1 PNG
        with open(os.path.join(options.inputs, "check.png"), "wb") as handle:
            handle.write(bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                       "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"))

    failures = 0
    try:
        for model in catalog["models"]:
            for variant in model["variants"]:
                for task, spec in model["tasks"].items():
                    job = {"id": "check", "task": task, "prompt": "a red fox in the snow", "values": {},
                           "image": "check.png"}
                    for item in spec["inputs"]:
                        if item.get("default") is not None and item["name"] not in ("prompt", "image"):
                            job["values"][item["name"]] = item["default"]
                    jobs = {"": job}
                    loras = next((item for item in spec["inputs"] if item["kind"] == "loras"), None)
                    if loras:
                        # Every slot filled, the first with a high and low pair
                        slots = [{"name": LORAS[0], "strength": 0.8} for _ in range(loras["slots"])]
                        slots[0]["low"] = LORAS[1]
                        jobs[" with LoRAs"] = dict(job, loras=slots)
                    for suffix, job in jobs.items():
                        prompt = page.build_prompt(model, variant, job)
                        label = f"{model['id']} {variant['id']} {task}{suffix}"
                        try:
                            answer = page.comfy_post("/prompt", {"prompt": prompt, "client_id": "check"})
                        except urllib.error.HTTPError as error:
                            failures += 1
                            print(f"FAIL {label}: {page.describe_rejection(error)}")
                            continue
                        print(f"ok   {label}")
                        page.comfy_post("/queue", {"delete": [answer["prompt_id"]]})
                        page.comfy_post("/interrupt", {})
                        time.sleep(0.5)
    finally:
        for path in made:
            os.remove(path)
    print(f"{failures} failed" if failures else "All taken")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

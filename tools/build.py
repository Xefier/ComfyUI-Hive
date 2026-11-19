#!/usr/bin/env python3
"""Makes comfyui-hive/catalog.json and comfyui-hive/workflows/ from tools/catalog-src.json and ComfyUI's own templates.

  python tools/build.py --templates <templates folder> --object-info <object_info.json>

- <templates folder>: the templates/ folder of the comfyui-workflow-templates-json package of the ComfyUI version the
  miner installs (the version in its requirements.txt).
- <object_info.json>: GET /object_info of that ComfyUI version, saved.

For every model and task of catalog-src.json it converts the template (convert.py), works out which model files the
workflow loads and where each comes from (the template's own download links), and asks Hugging Face for their sizes.
A variant's "replace" swaps files for another build of the same model (fp8 for bf16, ...); the replacement is taken
from the same folder of the same repository. Sizes of files in gated repositories need --hf-token.

Then tools/check.py tries every workflow on a real ComfyUI.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINER = os.path.join(ROOT, "comfyui-hive")


def template_files(template):
    """Every model file the template names, with its folder and link: {name: (dir, url)}."""
    found = {}
    graphs = [template["nodes"]] + [s["nodes"] for s in template.get("definitions", {}).get("subgraphs", [])]
    for nodes in graphs:
        for node in nodes:
            for model in (node.get("properties") or {}).get("models") or []:
                found[model["name"]] = (model["directory"], model["url"])
    return found


def used_names(prompt):
    names = set()
    for node in prompt.values():
        for value in node["inputs"].values():
            if isinstance(value, str):
                names.add(value)
    return names


size_cache = {}


def hf_size(url, token):
    """The size of a file on Hugging Face, from the listing of its folder."""
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    # <org>/<repo>/resolve/<revision>/<path...>
    org, repo, _, revision = parts[:4]
    path = "/".join(parts[4:])
    folder = os.path.dirname(path)
    key = (org, repo, revision, folder)
    if key not in size_cache:
        listing = f"https://huggingface.co/api/models/{org}/{repo}/tree/{revision}/{urllib.parse.quote(folder)}"
        request = urllib.request.Request(listing, headers={"User-Agent": "comfyui-hive-build"})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                entries = json.load(response)
        except urllib.error.HTTPError as error:
            print(f"  no listing of {org}/{repo}/{folder}: HTTP {error.code}", file=sys.stderr)
            entries = []
        size_cache[key] = {e["path"]: (e.get("lfs") or {}).get("size") or e.get("size") for e in entries}
    return size_cache[key].get(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates", required=True)
    parser.add_argument("--object-info", required=True)
    parser.add_argument("--src", default=os.path.join(ROOT, "tools", "catalog-src.json"))
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    options = parser.parse_args()

    with open(options.object_info, encoding="utf-8") as handle:
        info = json.load(handle)
    with open(options.src, encoding="utf-8") as handle:
        source = json.load(handle)

    os.makedirs(os.path.join(MINER, "workflows"), exist_ok=True)
    catalog = {"comfyui": source["comfyui"], "models": []}
    problems = 0
    for model in source["models"]:
        print(f"{model['id']}")
        files = {}  # name -> {name, dir, url, size}
        needed = set()  # names the workflows load, before any variant swaps them
        tasks = {}
        for task, spec in model["tasks"].items():
            if "like" in spec:
                # A task several models share, with this model's own keys added
                spec = dict(source["tasks"][spec["like"]], **{k: v for k, v in spec.items() if k != "like"})
                defaults = spec.pop("defaults", {})
                spec["inputs"] = [dict(item, default=defaults[item["name"]]) if item["name"] in defaults else item
                                  for item in spec["inputs"]]
            with open(os.path.join(options.templates, spec["template"] + ".json"), encoding="utf-8") as handle:
                template = json.load(handle)
            # Nodes the template has bypassed that this task needs (an image input left off by default)
            for node in template["nodes"]:
                if node["id"] in spec.get("enable", []):
                    node["mode"] = 0
            prompt, params = convert.convert(template, info)
            known = template_files(template)
            # A model of its own run through another model's template (a checkpoint for CheckpointLoaderSimple):
            # its file in place of the template's, kept in the same folder
            for old, own in model.get("files", {}).items():
                if old not in known:
                    print(f"  {task}: {old} is not loaded by {spec['template']}", file=sys.stderr)
                    problems += 1
                    continue
                known[own["name"]] = (known[old][0], own["url"])
                for node in prompt.values():
                    for name, value in node["inputs"].items():
                        if value == old:
                            node["inputs"][name] = own["name"]
            # Settings of the template this task always changes (a negative prompt, the sampler)
            for node_id, name, value in spec.get("set", []):
                prompt[node_id]["inputs"][name] = value
            # Skips the text encoder's last layers ("clip skip"), as a model like Pony is trained: a CLIPSetLastLayer
            # after the CLIP output named, which everything that took that output takes instead
            if "clip_skip" in spec:
                clip = spec["clip_skip"]["after"]
                takers = [(node, name) for node in prompt.values() for name, value in node["inputs"].items()
                          if value == clip]
                prompt["clip-skip"] = {"class_type": "CLIPSetLastLayer",
                                       "inputs": {"stop_at_clip_layer": spec["clip_skip"]["layer"], "clip": clip},
                                       "_meta": {"title": "CLIP skip"}}
                for node, name in takers:
                    node["inputs"][name] = ["clip-skip", 0]
            loads = used_names(prompt) & set(known)
            for name in sorted(loads):  # so the catalog comes out the same every time
                directory, url = known[name]
                files[name] = {"name": name, "dir": directory, "url": url}
            needed |= loads
            inputs = []
            for item in spec["inputs"]:
                entry = dict(item)
                if entry["kind"] == "loras":
                    # The slots and strength limits are the same for every model: said once in the source
                    entry = dict(source["loras"], **item)
                    outputs = [[node_id, 0] for node_id, *_ in entry["after"]]
                    if "clip" in entry:
                        if len(entry["after"]) != 1:
                            print(f"  {task}: LoRAs on the CLIP too need one model output, not a pair",
                                  file=sys.stderr)
                            problems += 1
                        outputs.append(entry["clip"])
                    for output in outputs:
                        if not any(value == output for node in prompt.values() for value in node["inputs"].values()):
                            print(f"  {task}: nothing takes output {output[1]} of node '{output[0]}', named for "
                                  "the LoRAs", file=sys.stderr)
                            problems += 1
                param = entry.get("param")
                if param is not None and param not in params and "." in param:
                    # "node.input" of a template without a subgraph
                    node_id, name = param.split(".", 1)
                    if node_id in prompt and name in prompt[node_id]["inputs"]:
                        params[param] = [[node_id, name]]
                if param is not None:
                    if param not in params:
                        print(f"  {task}: no setting '{param}' in {spec['template']}; it has {sorted(params)}",
                              file=sys.stderr)
                        problems += 1
                        continue
                    node_id, name = params[param][0]
                    value = prompt[node_id]["inputs"].get(name)
                    # The template's own value, unless the source gives one or the value comes from another node
                    # (a resolution picker, say)
                    if "default" not in entry and entry["name"] != "prompt" and not isinstance(value, list):
                        entry["default"] = value
                inputs.append(entry)
            workflow = f"{model['id']}-{task}.json"
            with open(os.path.join(MINER, "workflows", workflow), "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"template": spec["template"], "prompt": prompt, "params": params}, handle, indent=1,
                          ensure_ascii=False)
                handle.write("\n")
            tasks[task] = {"workflow": workflow, "inputs": inputs}
            print(f"  {task}: {len(prompt)} nodes, loads {sorted(loads)}")

        variants = []
        for variant in model["variants"]:
            replace = variant.get("replace", {})
            for old, new in replace.items():
                if old not in files:
                    print(f"  variant {variant['id']}: {old} is not loaded by the workflows", file=sys.stderr)
                    problems += 1
                    continue
                url = files[old]["url"]
                files[new] = {"name": new, "dir": files[old]["dir"], "url": url[: url.rindex("/") + 1] + new}
            names = sorted({replace.get(n, n) for n in needed})
            variants.append(dict({k: v for k, v in variant.items() if k != "files"}, files=names))
        for entry in files.values():
            entry["size"] = hf_size(entry["url"], options.hf_token)
            if not entry["size"]:
                print(f"  size of {entry['name']} unknown", file=sys.stderr)
        for variant in variants:
            total = sum(files[n]["size"] or 0 for n in variant["files"])
            print(f"  variant {variant['id']}: {len(variant['files'])} files, {total / 1024 ** 3:.1f} GB")
        catalog["models"].append(dict({k: v for k, v in model.items() if k not in ("tasks", "variants", "files")},
                                      tasks=tasks, variants=variants, files=files))

    with open(os.path.join(MINER, "catalog.json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(catalog, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {len(catalog['models'])} models" + (f", {problems} problems" if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

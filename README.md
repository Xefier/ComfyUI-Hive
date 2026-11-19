# ComfyUI-Hive

A Hive OS custom miner that runs [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instead of mining, so a rig
switches between Octa and making images and videos by changing flight sheet. Each rig serves a chat page: pick a model,
type a prompt (and attach an image to animate), and the result comes back on the page to watch and download.

Sister project of [Ollama-Hive](https://github.com/Xefier/Ollama-Hive), and built the same way: NVIDIA only, ComfyUI
runs in the foreground of Hive's miner screen, and no system service is installed, so with another flight sheet active
nothing of it runs or holds GPU memory.

## Flight sheet

One flight sheet for every rig: no model is chosen in it. Host `comfyui-hive-v0.5.tar.gz` somewhere the rigs can
download it (a GitHub release), then make a flight sheet with miner **Custom**:

- **Miner name:** `comfyui-hive`
- **Installation URL:** the link to the archive
- **Wallet, worker template, pool:** anything Hive accepts; they are ignored
- **Extra config arguments:** nothing, or any of the settings below

| Setting | Default | Meaning |
|---|---|---|
| `hf_token` | none | Hugging Face token, only for models whose download needs one (LTX-2.5). It can be given on the page instead |
| `port` | `8188` | ComfyUI's port. The chat page is on the next one (`8189`) |
| `bind` | the rig's private LAN address | Address to listen on |
| `allow` | the rig's own LAN | Comma-separated CIDRs allowed to connect, e.g. `192.168.1.0/24` |
| `data_dir` | `/var/lib/docker/comfyui-hive` | Where ComfyUI, the models and the outputs are kept |
| `gpus` | `0` | The GPU ComfyUI uses (one) |
| `torch_index` | `cu128` | PyTorch wheel index. `cu128` needs NVIDIA driver 570 or newer |
| `comfyui_version` | `v0.45.0` | The ComfyUI release. The workflows were made and checked for this one: change it only with a new version of this miner |
| `reset_oc` | `0` | `1` resets clock locks and power limits to default at start |
| `allow_docker` | `0` | `1` starts even with Docker containers running |

**Everything goes on the DOCKER drive**, `/var/lib/docker/comfyui-hive`: ComfyUI and its Python (about 8 GB), the
models (17 to 64 GB each), your own LoRAs (in `models/loras`, beside the ones the models bring) and what is made. If no drive is mounted at `/var/lib/docker` the miner waits and says so,
rather than filling the small OS drive; `data_dir=` puts it all somewhere else. It outlives flight sheet switches and new
versions of this miner.

## The page

`http://<rig>:8189/` (the miner log and the Hive dashboard say the link). Open it from any PC or phone on the LAN.

- **Models for this GPU** lists only the models that fit this rig's GPU, each in the build that fits it: a 32 GB card gets
  higher-precision builds than a 24 GB one, and a model no build of which fits isn't shown (the page says how many are
  hidden). Each card says what it can do, its build and its size.
- **Nothing is downloaded until you press Download** on a model (or say yes when a Claude session asks, see
  [Claude sessions](#claude-sessions)). It goes into the models folder with a progress bar
  and can be cancelled; a download that was cut off continues where it stopped. Files that two models share are
  downloaded once. **Delete** frees the space again, keeping files another downloaded model still uses.
- **The chat:** pick a downloaded model and what to make (text to image, edit image, text to video, image to video), write the
  prompt, and press Generate (or Ctrl+Enter). Size, length and seed can be changed; empty means the model's default
  and a random seed. Requests queue and run one at a time; each shows its progress (step, speed), then the image or
  video with **Download** and **Open** links, or what went wrong. The history stays on the rig.
- **Chats:** the requests are kept in chats, listed above the models. **New chat** starts one; it is named after its
  first prompt until you **Rename** it. Click a chat to open it; which chat is open is each browser's own, so a PC and
  a phone can be in different chats of the same rig. **Archive** takes a chat off the list without removing anything
  (**Show archived** brings the archived ones back to open or unarchive; a new request in one unarchives it).
  **Delete** removes the chat with its requests and the images and videos they made, unless a request is waiting or
  running in it. The requests from before chats, and those of the Claude Code tools, are in a chat named General.
- **Outputs** (the link at the top, `http://<rig>:8189/#outputs`) lists every file in the outputs folder, newest first:
  a preview, its size and date, the prompt, model and chat it came from (files made in ComfyUI's own editor are listed
  too), with **Download** and **Open**. **Delete** removes one, or tick several (or **Select all**) and **Delete
  selected**; the page says how much the selection takes. A request whose file was deleted says so in its chat.
- **Size:** the **Size** list has common sizes by shape (16:9, 9:16, 1:1, 4:3, 3:4, 21:9), only those the model takes,
  each rounded to the multiple it needs (16 or 32); Width and Height can also be typed.
- **The image for image to video or to edit:** drop it on the chat, paste it (Ctrl+V, from a screenshot or a copied image), or
  choose a file. A preview shows it with its size; it stays attached across task and model switches until **Remove**.
  Pasting or dropping an image while on a text task switches to the model's task that starts from one (image to
  video, or edit image for Qwen-Image). Images other than
  PNG, JPEG and WebP are turned into PNG first. Two buttons fit the video's size to the image:
  - **Use image size**: the image's own width and height, so the video starts from the exact image. A bigger image
    than the model takes is scaled down to fit, keeping its shape.
  - **Match aspect ratio**: the image's shape at the current resolution, keeping the shorter side of the size set now.
    Video models are made for a class of size named by that side (480p, 720p), which the time and memory follow, so
    1280 × 720 with a portrait image becomes 720 × 1280.

  Either way each side is rounded to the model's multiple, and the page says when it scaled or rounded. MiniMax H3's
  image-to-video and Qwen-Image's editing take their size from the image by themselves, so they have neither button.
- **Edit image** (Qwen-Image 2.1 Turbo): attach the image and say in the prompt what to change ("make it night",
  "replace the car with a bicycle", "remove the text"); the result keeps the image's size. A prompt-refining model
  first turns the instruction into a fuller one, as in ComfyUI's own template.
- **LoRAs:** Wan 2.2 (14B and 5B) and HunyuanVideo 1.5 take up to 3 of your own LoRAs per request, in **LoRAs**
  under the task buttons: each slot is a file and a strength (1 by default, negative allowed), set with the slider (-5 to 5, for slider LoRAs
  that are used at either side of 0; double-click it to go back to 1) or typed (-10 to 10); a slot left on "none"
  isn't used. They are added on top of what the model's workflow already applies, the Wan 2.2 14B speed-up LoRAs
  included. Wan 2.2 14B is two models, a high-noise and a low-noise one, and every LoRA goes to both: a LoRA that comes
  as one file (a Wan 2.1 LoRA, say) is used for both, and for one that comes as a high and a low file, pick the high
  file in the slot and the low file under **low noise**. Only the video model is changed, not the text encoder
  (ComfyUI's `LoraLoaderModelOnly`). A request in the history says which LoRAs it used.
  - **Adding one:** drop a `.safetensors` file on the chat or choose it in the LoRAs box; it uploads into the rig's
    `models/loras` folder with a progress bar and can be cancelled. 8 GB at most each, `.safetensors` only, and
    the name keeps only letters, digits, spaces and `. _ - + ( )`. A file copied into that folder by hand (in a
    subfolder too) is listed as well. **Delete** removes one, unless a waiting or running request uses it.
  - They are apart from the models' Download and Delete: deleting a model never removes one of your LoRAs, and the
    LoRAs a model brings aren't in this list.
- **Switching model** is picking another card. The rig lets go of the last model's memory first, so the first request
  on a new model takes longer while it loads.
- The page also links ComfyUI's own editor (`http://<rig>:8188`), for building or changing workflows by hand, and shows
  the end of the miner log.

The page and ComfyUI have no login: like Ollama-Hive's API, anything on the LAN that can reach them can use them,
including starting a download, deleting a model, a chat or an output, and uploading or deleting a LoRA. They listen only on the private LAN address, and `allow=` limits
which addresses can connect.

## Claude sessions

Claude Code sessions on your PCs can make images and videos on the rigs too. On each PC, clone or pull this repo (needs
Claude Code and Python 3.8 or newer; nothing to install), then either ask Claude in this repo's folder ("add the rig at
192.168.1.189", or `/comfyui-hive add 192.168.1.189`) or run it yourself from the repo's folder:

```powershell
.\client\comfyui-hive.cmd add 192.168.1.189 192.168.1.232
```

| Command | Does |
|---|---|
| `comfyui-hive add <address>[:port] ...` | Adds rigs; the page's port 8189 unless given. Registers the MCP server on first use |
| `comfyui-hive remove <address>[:port] ...` | Removes rigs; removing the last one unregisters the server |
| `comfyui-hive list` | Lists the rigs, whether each answers, and its downloaded models (also what a double-click does) |
| `comfyui-hive unregister` | Removes every rig and the server |

It registers for the current Windows user, in every project. New sessions then get five tools:

- `comfy_status`: each rig, its GPU, the models downloaded on it with what they can make and their settings' limits,
  the models that could be downloaded, and the requests running or waiting.
- `comfy_generate`: makes an image or a video and saves it on this PC, returning the file's path. The session gives
  the prompt, the model (it can be left out when only one downloaded model can do the task), the task (`t2i`, `edit`,
  `t2v`, `i2v`), an image path for image to video or to edit, and optionally size, length or duration, and seed. It goes to the least
  busy rig that has the model. It waits with progress (step and speed) for up to 30 minutes; with `wait: false` it
  returns at once with a job id.
- `comfy_result`: waits for such a job and saves its result.
- `comfy_cancel`: stops a job.
- `comfy_download`: downloads a model onto a rig, **only with your yes**. In the Claude Code CLI the tool asks you
  itself in a dialog (MCP elicitation), naming the model, the rig, the size and the rig's free space, so a session
  can't download by deciding to; a no there is final. Where the client shows no such dialog (some surfaces cancel
  the question by themselves), the session has to ask you in the conversation and the tool refuses until it says you
  agreed. `comfy_status` then shows the download's progress.

Only models downloaded on a rig can be used: if none has the one a request needs, the session asks you whether to
download it. Results go to `Videos\ComfyUI-Hive` (set `COMFYUI_HIVE_OUT` in your
environment before `add` for another folder). An image to animate or edit is read only from the session's folder, the results
folder (so an image it made can be animated next), Pictures, Downloads, Desktop and Claude's scratch folders. After
pulling a client change, new sessions pick it up; after moving the clone, run `add` again.

## Models

| Model | Makes | 4090 (24 GB) | 5090 (32 GB) | Download | Notes |
|---|---|---|---|---|---|
| Wan 2.2 14B | text/image to video, 16 fps | fp8 | fp8 | 64 GB | Both experts and the 4-step speed-up LoRAs, for both tasks. Takes your LoRAs |
| Wan 2.2 5B | text/image to video, 720p 24 fps | fp16 | fp16 | 17 GB | Takes your LoRAs |
| HunyuanVideo 1.5 | text/image to video, 720p 24 fps | fp16 run as fp8 | fp16 | 43 GB | Takes your LoRAs |
| LTX-2.5 | text/image to video with sound | not offered | int8 | 42 GB | Gated: accept the license at [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) and give the account's token. Free for organisations under $10M yearly revenue |
| MiniMax H3 | text/image to video with sound, text to image | pruned w6a8 | pruned int8 | 39 / 44 GB | Commercial use of what it makes needs a MiniMax license (sold through Comfy) |
| Z-Image Turbo | text to image | bf16 | bf16 | 19 GB | |
| Qwen-Image 2.1 Turbo | text to image, up to 2K; edit image | int8 | bf16 | 34 / 40 GB | Editing has its own prompt-refining text encoder, included in the download |

The workflows are ComfyUI's own templates for each model, as its editor offers them (with their defaults: speed-up LoRAs
on, sizes, lengths); only the prompt, image, size, length and seed are set by the page, and your LoRAs added. **Which build fits which card is
an estimate** from the files' sizes and the templates' own notes (the Wan 2.2 template measured its fp8 build at 84% of
a 24 GB card), not yet measured on these rigs. If a model runs out of memory on a card, raise its `min_vram_gb` in
`tools/catalog-src.json` and build again.

## What happens on a switch

**Switching to this flight sheet:** it waits while any GPU process or Docker container is running, so it can't take a
GPU from a rental (a backstop only: take the node off the market first), and while no DOCKER drive is mounted. Then it
sets the firewall rules for both ports, stops `hive-watchdog`, installs Python and starts the page, installs ComfyUI and
PyTorch the first time (or after a version change), and starts ComfyUI on the private LAN address.

**Switching away (or a stop or reboot):** ComfyUI and the page end, a download in progress stops (it continues next
time), the firewall rules go, and the watchdog starts again if it was running. `h-guard.sh` does the same if `h-run.sh`
is killed outright. A request that was running is marked failed.

**Dashboard:** while a request runs, the GPU's hashrate is the sampler's speed in steps per second (`it/s`, so a slow
video model shows a fraction of 1 H/s), and 0 otherwise. The algo field says what the rig is doing (`comfyui ready`,
`comfyui generating 3/8 wan2.2-14b t2v`, `comfyui downloading ltx-2.5 42%`, `comfyui installing`), and
accepted/rejected count the requests done and failed since the miner started.

Hive applies overclocks from the OC profile, not the flight sheet: use a stock profile while on this flight sheet or set
`reset_oc=1`. With the watchdog stopped, nothing reboots the rig if a GPU drops out.

## Adding or changing a model

The miner ships ready-made API workflows (`comfyui-hive/workflows/`) and `comfyui-hive/catalog.json`, both made by
`tools/build.py` from `tools/catalog-src.json` and ComfyUI's own workflow templates:

1. Get the templates of the ComfyUI version (the `comfyui-workflow-templates-json` package its `requirements.txt`
   names) and that version's node definitions (`GET /object_info` of a running ComfyUI, saved as a file; a CPU-only
   ComfyUI is enough).
2. Add or change the model in `tools/catalog-src.json`: the template of each task, which of the template's settings the
   page sets (`param`: a label shown on the template's subgraph, or `node.input`), and its builds, best first, with the
   GPU memory each needs and the files they swap. For a task to take the user's LoRAs, give it an input of kind
   `loras` whose `after` names the node whose model output they are chained onto (two nodes, the second marked
   `"low"`, for a high-noise and low-noise pair); `page.py` adds the loader nodes when a request is sent, so there
   is one workflow per task whatever the number of LoRAs.
3. `python tools/build.py --templates <templates folder> --object-info <object_info.json>` converts the templates
   (`tools/convert.py` expands their subgraphs into the API format), works out which files each workflow loads and their
   sizes on Hugging Face.
4. `python tools/check.py --comfy http://<that ComfyUI> --models <its models folder> --inputs <its input folder>` sends
   every model, task and build to that ComfyUI, which checks each node, input and file name, and says what it refuses.
   It uses empty stand-ins for the model files, so nothing is downloaded. A task that takes LoRAs is sent twice,
   without any and with every slot filled.

## Checks on a rig

```bash
miner log
```

```bash
curl -s http://$(cat /run/comfyui-hive/address):8188/system_stats | jq
```

## Files

- `h-run.sh`: start-up checks, the install, then runs ComfyUI and the page
- `page.py`, `page.html`: the chat page, the downloads, your LoRAs, and the requests to ComfyUI
- `catalog.json`, `workflows/`: the models and their workflows, made by `tools/build.py`
- `h-stop.sh`: puts the rig back; safe to run repeatedly
- `h-guard.sh`: runs `h-stop.sh` if `h-run.sh` is killed, and keeps the watchdog off meanwhile
- `h-stats.sh`: dashboard stats
- `h-config.sh`: checks the flight sheet settings and writes `comfyui-hive.conf`
- `h-common.sh`, `h-log.sh`: settings, paths and helpers they share
- `client/comfyui_hive_mcp.py`: the Claude Code tools (MCP server, runs on the PC); `client/comfyui-hive.cmd` / `.ps1` register it

Build the archive with `Archive.bat`, then rename it to `comfyui-hive-v<version>.tar.gz`: Hive reads the miner's name
and version from the file name.

## Tested

On a PC with an RTX 5090, in WSL (Ubuntu 20.04), with ComfyUI v0.45.0:

- every model, task and build of the catalog is taken by ComfyUI (`tools/check.py`, with empty stand-ins for the model
  files);
- `h-run.sh` from start to stop, in a test root with `data_dir=`: the wait for a DOCKER drive, the install of Python,
  ComfyUI and PyTorch `cu128` (2.11, CUDA working), ComfyUI started on the GPU, the page, and a stop that leaves nothing
  running. Without root, the firewall rules failed and it went on with the warning, as meant;
- the page: lists the models that fit (and the builds a 24 GB card would get), downloads a file from Hugging Face, runs
  a request through ComfyUI and serves the result, follows ComfyUI's progress messages, shows ComfyUI's reason when a
  request fails, and refuses requests for models that aren't downloaded or don't fit.

For the LoRAs (v0.3), with a CPU-only ComfyUI v0.45.0 and an RTX 4090 rig running v0.1 of this miner:

- every task that takes LoRAs is taken by ComfyUI with every slot filled, the first with a high and low pair
  (`tools/check.py`);
- the page: upload (progress, the name cleaned, refusals for a wrong type, a duplicate and a file that isn't
  safetensors inside), the list, Delete, and the slots surviving the page's refresh;
- on the rig's ComfyUI, a Wan 2.2 14B text-to-video workflow built by `page.py`, without a LoRA and with a high and low
  pair in a slot (the speed-up LoRAs' own files, for want of another): ComfyUI reported 0 and 400 patches on each of
  the two models, and both videos were made.

Not run for the LoRAs: v0.3 itself on a rig (the upload of a real, large file to it, a request through its page), a
LoRA of your own, and Wan 2.2 5B or HunyuanVideo 1.5 generating with one.

For image editing and `comfy_download` (v0.4), with a CPU-only ComfyUI v0.45.0: every workflow, Qwen-Image's edit in
both builds included, is taken by ComfyUI (`tools/check.py`); an edit request from the page and from the Claude tools
reaches ComfyUI and fails only at loading the empty stand-in model files; the page switches to Edit image when an image
is pasted on Qwen-Image. `comfy_download` against the page, with a small real file from Hugging Face: a yes and a no in
the dialog, a dialog the client cancels by itself (then the session's yes in the conversation), and a refusal without
any yes. Not run: a real edit, and the dialog in a real Claude Code session.

For the chats and the Outputs view (v0.5), the page run on a PC without ComfyUI, on a made-up history and image files:
the history from before chats opens as General; a new chat, its name from the first prompt, rename, archive and
unarchive, delete (its requests, their files and the image one started from are gone); the outputs listed with their
requests, one and several deleted, paths outside the outputs folder refused; a request without a chat (the Claude
tools) lands in General. Not run: requests that finish in a chat, video previews, and any of it on a rig.

Not yet run: a real model generating (no model has been downloaded and run), the memory each build really needs, the
dashboard stats (no `jq` where it was tested), and anything on a real Hive rig (firewall rules, watchdog).

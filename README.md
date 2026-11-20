# ComfyUI-Hive

A Hive OS custom miner that runs [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instead of mining, so a rig
switches between Octa and making images and videos by changing flight sheet. Each rig serves a chat page: pick a model,
type a prompt (and attach an image to animate), and the result comes back on the page to watch and download.

Sister project of [Ollama-Hive](https://github.com/Xefier/Ollama-Hive), and built the same way: NVIDIA only, ComfyUI
runs in the foreground of Hive's miner screen, and no system service is installed, so with another flight sheet active
nothing of it runs or holds GPU memory.

## Flight sheet

One flight sheet for every rig: no model is chosen in it. Host `comfyui-hive-v1.1.tar.gz` somewhere the rigs can
download it (a GitHub release), then make a flight sheet with miner **Custom**:

- **Miner name:** `comfyui-hive`
- **Installation URL:** the link to the archive. It can stay the same from then on: the miner updates itself (see Updates)
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
| `peers` | none | Other rigs of this miner that aren't found by themselves (another subnet): comma-separated addresses, e.g. `10.0.2.15,10.0.2.16` |
| `hub` | none | The hub this rig works for (xefier-comfyui on a PC or server of the LAN): its address, with `:port` if not 8189, e.g. `192.168.1.10`. The rig then fetches the worker program from the hub and keeps it at the hub's version, and the hub hands it requests. With `allow=` set, the hub's address must be in it. Without a reachable hub the rig runs the program of this miner as before |

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
  and a random seed. Requests queue and run one at a time; each shows its progress, then the image or
  video with **Download** and **Open** links, or what went wrong. The history stays on the rig.
- **Progress:** one bar for the whole request, full when it is done: loading the model, every pass of steps (Wan 2.2
  14B and LTX have two) and the decoding and saving after them, with the step over all passes, the pace, the time
  gone and about how long is left. The time left comes from this request's pace and from how long the load and the
  end took in the last request like it (same model and task; same settings for the end), so the first request of a
  kind fills the bar by its steps, says "a rough guess", and has no estimate before its first step. The bar never
  goes back; when a request takes longer than estimated it waits just short of full.
- **A LoRA's trigger prompt:** beside a slot's strength, **Set trigger prompt** asks once for the words the slot's
  LoRA is called up with and keeps them on the rig with the file; from then on **Use trigger prompt** adds them to the
  end of the prompt (not twice), and **Edit** changes or removes them. Every browser sees the same ones; each rig
  keeps its own.
- **A photo as the image:** on a phone or tablet the image box has **take a photo** beside "choose a file": it
  opens the camera, and the picture taken is attached.
- **A request again:** **Use again** under a request puts its prompt, model, task, numbers, seed, LoRAs and image
  back in the composer (clear Seed for a different result). **Use as input** under an image the rig made attaches it,
  switching to the model's task that starts from an image. Each request shows the size and numbers it was made with.
- **A video continued:** **Continue**, under a video beside Download, does the same as Use again but starts
  from the last frame of that video, with a new seed: to go on where it ended. The request made this way is a video of
  its own; with **Also make one stitched video of them in a row** ticked (it is, until you untick it), the rig also makes one video of the whole
  row when it is done: every video continued up to this one, one after another, the frame they share left out once,
  with their sound. It is made from the videos themselves each time, never from an earlier stitched one, with PyAV,
  which ComfyUI has installed. The chat shows only the stitched video under such a request: the part it added is in
  it, stays on the rig for the next stitching, and is listed in Outputs. The last frame is taken as the browser plays the video, so a little softer than the
  model made it.
- **Continued from a moment before the end:** the row over the image, *Continues that video from … s*, takes the
  second to go on from (empty: the last frame), and shows the video's length. Or open the video large, pause it at
  the moment, and click **Continue from here** under it. The image becomes the frame shown at that second, and a
  stitched video has the continued one up to that frame only. Continue from here on a stitched video finds the
  request whose part that moment is in (one stitched before this was added can only be continued from its end).
- **A request taken to another rig:** with **Other rigs** on, a list of the rigs stands beside Use again (Continue goes by it too),
  set to the open chat's own. With another rig chosen, they start a new chat on that rig, named after this one, with
  the request's prompt, settings and the image it started from (for Continue, the video's last frame). A LoRA that rig
  doesn't have is left out and said; a model it doesn't offer leaves the prompt and image for another model. A video
  continued on another rig isn't stitched with this one: each rig only has its own files.
- **A file deleted from the chat:** **Delete** at the right of a file's links under a request deletes it from the
  rig, after asking.
- **Every image hidden:** the eye with a line through it at the top (or Alt+X) hides every image and video on the
  page and pauses the videos, until it is pressed again. The browser remembers it.
- **After a request that failed or was stopped**, the rig has ComfyUI unload its models and give the GPU's memory
  back, so the next request starts clean: one that ran out of memory used to leave the GPU full, and the next request
  of the same model failed the same way or never got past loading.
- **The queue:** a waiting request says how many are before it and, once requests like them have been timed, about
  when it starts.
- **Without looking:** the tab's title shows how far the open chat's request is ("46% · ComfyUI-Hive"), "Working"
  while another chat is busy, and "Done" when one ended while the tab was in the background. **Sound when done** (at
  the top, remembered by the browser) plays a short sound. Browser notifications aren't used: browsers only allow
  them on https pages, and the rig's page is plain http on the LAN.
- **Looking at results:** images and videos are shown as thumbnails, a video as a still with a play mark. Click one
  to see it large (on a phone, filling the screen), where a video plays, with the arrow keys or the buttons going
  through the chat's other results, and Esc or Back to close. The same in the Outputs view. **Thumbnails** under the
  gear sets their size: small on a phone to begin with, and the browser remembers it. **Input image** beside it sets
  how big the image a request starts from is shown over the prompt.
- **A result marked or hidden:** under each image and video, beside its links, are a star (a favorite, gold), a
  thumbs up (green) and a thumbs down (red). One of them at most: the one chosen stays there alone until it is clicked
  again, which takes the mark off and brings the other two back. **Hide** folds only that image or video away, its
  links staying, until **Show**; a thumbs down hides it too. **Favorites** and **Liked**, under the gear and as tabs of
  the Outputs view, list everything with the star and with the thumbs up; a mark can be taken off there as well. The
  marks are kept on the rig, so every device sees them.
- **The prompt being written** is kept with the chat like its other settings.
- **Models to download** are folded under the ones on the rig ("7 more to download").
- **Every rig on one page:** the rigs running this miner find each other on the LAN (each announces itself by a
  broadcast on the page's port, UDP; `peers=` names the ones on another subnet). When a rig has found others, **Other
  rigs** appears at the top of its page. Turned on (the browser remembers it), the list shows every rig's chats with
  the rig's name beside each, and opening one turns the whole page to that rig: its models, LoRAs, queue, progress,
  outputs and rental warning. **New chat** gets a choice of the rig to start it on. A chat stays on the rig it was
  started on, and a request sent this way says on its own rig's page whose page it came from. The browser only talks
  to the rig whose page is open, which passes everything on, so it works from anywhere that rig's page does. Every rig
  needs this version, and with `allow=` set, the rigs' own addresses must be in it for them to reach each other.
- **Progress in the list of chats:** a chat with a request under way has a bar on its card in the list, with how far
  it is and the time left, or "waiting its turn" behind another request: every rig's work at a glance.
- **Finished, until looked at:** when a chat's request ends, its card in the list gets a mark beside its name,
  **finished** or **failed**, which goes away when the chat is opened. The open chat gets none, unless it ended while
  the browser's tab was in the background. Each browser keeps its own account of what was looked at, and only what
  ends after a chat was first seen there is marked.
- **One scroll bar:** on a desktop screen the page itself doesn't scroll, only the chat's messages do (and the side
  panel when its lists are longer than the window). A phone scrolls as one page.
- **On a phone:** the page opens on the list of chats; a chat opens as a screen of its own, with an arrow (or the
  phone's Back) to return to the list, and the models are a screen reached from the gear. A chat's Rename, Archive and
  Delete are behind the three dots on its card.
- **The top row:** Comfy's mark and the worker's name, which has the row to itself (the page's title is no longer
  written there), with an arrow that opens the rig's state: VRAM, GPU load, RAM
  and disk as bars, the GPU, ComfyUI and the version. Folded to begin with, and a rig that doesn't answer, has no GPU
  or may be rented still shows. The gear at the top right holds Other rigs, Sound when done, Thumbnails, Outputs, the
  miner log and the ComfyUI editor; it and the eye stay in their corner when the page scrolls. **+** starts a chat,
  with a choice of the rig when Other rigs is on.
- **A request repeated:** **Repeat** beside Generate makes the request that many times (20 at most). As it is, they
  are separate tries of the prompt, each with a seed of its own, all queued at once. For a video, with **Each
  continues the one before** ticked, they are a row: each starts from the last frame of the one before, which the rig
  takes from the video itself, so the row goes on with the page closed. With the stitched video ticked too, each one
  from the second on also gives the stitched video of the row so far. Only the one being made is queued, the next
  when it is done: one that fails or is stopped ends the row.
- **A rental is never interrupted by a request:** before a request is taken, and again before one that waited in the
  queue starts, the rig checks what it checks before starting ComfyUI: a GPU process that isn't ComfyUI, or a running
  Docker container (unless `allow_docker=1`). If there is one, the request is refused with what was found and nothing
  starts. This holds for the Claude Code tools too. The page shows a warning above the chat and turns Generate off
  within about ten seconds of one being found.
- **Chats:** the requests are kept in chats, listed above the models. **New chat** starts one; it is named after its
  first prompt until you **Rename** it. Click a chat to open it; which chat is open is each browser's own, so a PC and
  a phone can be in different chats of the same rig. **Archive** takes a chat off the list without removing anything
  (**Show archived** brings the archived ones back to open or unarchive; a new request in one unarchives it).
  **Delete** removes the chat with its requests and the images and videos they made, unless a request is waiting or
  running in it. The requests from before chats, and those of the Claude Code tools, are in a chat named General.
- **Each chat has its own settings:** the model, what to make, the size and the other numbers (kept per model and
  task within the chat), the seed, the LoRAs with their strengths, and the image last attached in it. They are kept
  on the rig with the chat, so opening it again, after a reload or on another PC or phone, brings them back. A chat
  that has none yet (a new one, or one from before this) starts from what is set at that moment, without the image.
  A request from the Claude Code tools with an image makes it the image of General.
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
- **LoRAs:** Wan 2.2 (14B and 5B), HunyuanVideo 1.5, SDXL 1.0, Pony Diffusion V6 XL and SD 1.5 take up to 3 of your own LoRAs per request, in **LoRAs**
  under the task buttons: each slot is a file and a strength (1 by default, negative allowed), set with the slider (-5 to 5, for slider LoRAs
  that are used at either side of 0; double-click it to go back to 1) or typed (-10 to 10); a slot left on "none"
  isn't used. They are added on top of what the model's workflow already applies, the Wan 2.2 14B speed-up LoRAs
  included. Wan 2.2 14B is two models, a high-noise and a low-noise one, and every LoRA goes to both: a LoRA that comes
  as one file (a Wan 2.1 LoRA, say) is used for both, and for one that comes as a high and a low file, pick the high
  file in the slot and the low file under **low noise**. The page goes by the file names (`high`/`low` as a word in the
  name, as in `..._high_noise.safetensors`): picking either half of a pair whose other half is on the rig puts the high
  one in the slot and the low one under **low noise**, and a half used alone, a pair the wrong way round, or a pair's
  file on a model other than Wan 2.2 14B gets a warning under its slot. A half alone does little: the high-noise model
  makes the shapes and the motion, and gets the low-noise file too. On the video models only the video model is changed, not the
  text encoder (ComfyUI's `LoraLoaderModelOnly`); on SDXL, Pony and SD 1.5 a LoRA changes the text encoder too, at
  the same strength (`LoraLoader`), as LoRAs for those expect. A request in the history says which LoRAs it used.
  - **Which model a LoRA is for:** a LoRA works only on the family it was trained for, which its Civitai page gives
    as the base model: "SD 1.5" for SD 1.5, "SDXL 1.0" for SDXL, "Pony" for Pony Diffusion V6 XL, "Wan Video" for Wan
    (a Wan 2.1 14B LoRA works on Wan 2.2 14B too), "HunyuanVideo" for HunyuanVideo. One for another family
    fails no request: ComfyUI finds nothing it fits and it simply changes nothing. Pony and SDXL LoRAs load on each
    other's model but work poorly there.
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

## Updates

The miner updates itself, so the flight sheet's installation URL never has to change again: any release from v1.0 on
keeps itself at the newest one. About every quarter of an hour, and once before it starts, it asks GitHub for this
repository's newest release; a newer one is downloaded, the miner's folder is replaced by it (Hive's config for the
miner is kept), and the miner starts again as the same process, which takes about as long as a switch of flight sheet.

- **Update automatically**, under the gear, is on until you turn it off: the update is taken by itself.
- With it off, the gear says which version is available and offers **Update**.
- Either way it waits until nothing is being made or downloaded and the rig isn't rented, and says what it waits for.
- A release that can't be downloaded or isn't whole changes nothing: the miner keeps running as it is and says why.

A rig that works for a hub (`hub=`) still gets its worker program from the hub; this update is of the miner's own
scripts and the program it falls back to.

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
| SDXL 1.0 | text to image, 1024 px | fp16 | fp16 | 6.5 GB | Stability's base model. Takes your LoRAs (SDXL) |
| Pony Diffusion V6 XL | text to image, 1024 px | fp16 | fp16 | 6.5 GB | SDXL-based, prompted with tags: start with `score_9, score_8_up, score_7_up`. Clip skip 2 and Euler a, as its author advises. Takes your LoRAs (Pony) |
| SD 1.5 | text to image, 512 px | fp16 | fp16 | 2 GB | Takes your LoRAs (SD 1.5) |

SDXL, Pony and SD 1.5 share ComfyUI's SDXL template (one checkpoint, prompt, sampler, decode), with the page also
setting the steps and CFG and a fixed negative prompt per model. The workflows are ComfyUI's own templates for each model, as its editor offers them (with their defaults: speed-up LoRAs
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

The catalog, the workflows and the `tools/` that make them are in `xefier-comfyui`: this is done there.

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
   is one workflow per task whatever the number of LoRAs. Give it `clip` (the text encoder's output) for LoRAs that
   change the text encoder too. A model with no template of its own can use another's: `files` puts its file in
   place of the template's (a checkpoint for the SDXL template), a task's `set` changes the template's settings
   (the negative prompt, the sampler) and `clip_skip` skips the text encoder's last layers. Models sharing a task
   name it once in `tasks` and refer to it with `like`.
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
- `page.py`, `page.html`, `catalog.json`, `workflows/`: the page program, its models and their workflows. They are
  not kept in this repository: `release.sh` puts them into the package from `xefier-comfyui`, where they are made
  (and where `tools/` is)
- `h-stop.sh`: puts the rig back; safe to run repeatedly
- `h-update.sh`: the miner updating itself to the newest release
- `h-guard.sh`: runs `h-stop.sh` if `h-run.sh` is killed, and keeps the watchdog off meanwhile
- `h-stats.sh`: dashboard stats
- `h-config.sh`: checks the flight sheet settings and writes `comfyui-hive.conf`
- `h-common.sh`, `h-log.sh`: settings, paths and helpers they share
- `client/comfyui_hive_mcp.py`: the Claude Code tools (MCP server, runs on the PC); `client/comfyui-hive.cmd` / `.ps1` register it

Build the package with `bash release.sh`: it makes `comfyui-hive-v<version>.tar.gz` from what is committed here and
the page program committed in the clone of `xefier-comfyui` (at `../../../xefier-comfyui`, or where `XEFIER_COMFYUI`
says). Hive reads the miner's name and version from the file name.

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

For SDXL 1.0, Pony Diffusion V6 XL and SD 1.5 (v0.6), with a CPU-only ComfyUI v0.45.0 on Windows: every workflow of the
catalog is taken by ComfyUI (`tools/check.py`), the three new ones also with all 3 LoRA slots filled; the workflow
`page.py` builds for Pony with two LoRAs chains checkpoint, `LoraLoader`s (model and text encoder, a negative strength
passed through), clip skip, prompts and sampler as meant; the other models' workflows come out of `tools/build.py`
unchanged. Not run: a download of the three on a rig, a real image from any of them, and a real LoRA on them.

For the high and low pairing (v0.6), the page run on Windows with stand-in LoRA files, in a browser: picking a low-noise file
whose high-noise file is on the rig fills the slot with the high one and **low noise** with the low one; a low-noise file
alone is warned about on Wan 2.2 14B, and both halves on Wan 2.2 5B; a file that isn't a half gets no warning; no
errors in the browser's console.

For the page's polish (use again, use as input, the queue's wait, the title, the viewer, the prompt kept per chat,
the folded models, the new look), the page run on a PC against the same stand-in for ComfyUI, in a browser, dark and
light and at a phone's width: each tried once and working, with no errors in the console. The rental warning was
shown by setting it by hand, and the sound was turned on but not listened to. Not run: any of it on a rig.

For every rig on one page (v0.8), two copies of `page.py` on one PC, each told of the other with `peers=`, without
ComfyUI: each lists the other by name; a chat started and renamed on the second through the first, and opened from the first one's page;
the page turning to the second rig's models and back; a request sent to the second through the first, recorded there
with the first's name (it then fails for want of a ComfyUI); a 1 MB range of a file and a 3 MB LoRA upload passed on
unchanged; an address that isn't a known rig refused; **Other rigs** turned off and on; and the second rig stopped
while its chat was open, which says it doesn't answer and lets another chat be opened. Not run: any of it on a rig,
the broadcast by which rigs find each other (two copies on one PC can't share the port), the worker's name read from
Hive, and a video played through another rig.

For the bars in the list of chats (v0.9), with made-up requests: the rig's numbers for a chat with a running, a
waiting and a finished request, and the cards drawn for each, one of another rig among them, filling without the list
being built again. Not run: a real request, and any of it on a rig.

For Continue and stitching (v0.10), on a PC with videos made for the test, with and without sound, and PyAV 12 (a rig
has 14 or newer): two and three stitched with the right number of frames and length of sound, videos of different
sizes refused, a row of requests stitched from their own videos, and one whose earlier video is gone saying so. On
the page: Continue attaching the right last frame, the request carrying which one it continues and the choice to
stitch, and a stitched request continued from its own video. Delete in the chat and the eye (with Alt+X) were tried
on the same page. Not run: a continued request taken and made by a rig, stitching on a rig, and any of it through
another rig.

For a request taken to another rig (v0.11), between two copies of `page.py` on one PC: Use again with the second rig
chosen starting a chat there with the first's name, the prompt, seed, size and image, a LoRA the second doesn't have
left out; and Continue arriving there with the video's last frame and no seed. Not run: a request made from such a
chat, a model the other rig doesn't offer, and any of it on a rig.

For the mark of a finished chat (v0.12), on a PC with made-up requests: none on the first visit, **finished** and
**failed** on chats whose last request ended after they were looked at, none for a cancelled one or the open chat, and
the mark gone after opening the chat. Not run: a request that ends while the page is open, and any of it on a rig.

For a stitched request showing only its stitched video (v0.13), on a PC with a made-up one: the stitched video alone
under it, Continue still offered, and its own part shown again once the stitched video is deleted.

For the phone's screens, the top row, the gear and the thumbnails (v0.14), in a browser at a phone's size and a
desktop's, between two copies of `page.py`: the list, a chat's screen and back by the arrow and by Back, the models
from the gear, the viewer filling the screen and closing on Back, the state folded and opened with its bars (RAM
read from a sample of `/proc/meminfo`, there being none on the PC), the plus with its choice of rig, and the size of
the thumbnails from the slider. Not run: a phone itself, iOS Safari (whether a video's thumbnail shows a frame
there), and touch.

For Repeat (v0.14), with the making of a video replaced by a stand-in that writes a small one, and PyAV 12: a row of
3 with and without the stitched video, each from the last frame of the one before; 3 separate tries; a row of 4 that
ends at its failed second; more than 20, and a row on a model that can't start from an image, refused. Not run: a
real request, a row's running one stopped, and any of it on a rig.

For a LoRA's trigger prompt (v0.17), on a PC with stand-ins for LoRA files: set, added to a prompt once and not
twice, changed, removed, the asking cancelled, and one for a file that isn't on the rig refused. Not run: with a real
LoRA, and on a rig.

For the GPU's memory given back after a failed request (v0.18), with ComfyUI's answers played: asked to unload after
one that ran out of memory, one that was stopped, and one failing with ComfyUI unreachable; not after one that
finished. Not run: on a rig, where it was reported.

For `hub=` (v0.19), the part of `h-run.sh` that fetches the worker program, run in Git Bash against a hub on a PC:
fetched when the rig has none, left alone at the hub's version, not replaced while a request is being made, replaced
when idle, and kept when the hub can't be reached. Not run: on a rig, and the page started from the fetched program
there.

For the progress bar, the page run on a PC against a stand-in for ComfyUI that plays a load, two passes of 4 steps
with a pause between them, and an end: the first request of a kind fills by its steps and says so; the next one like
it fills once from start to end with the time left counting down to within a few seconds, and the bar never goes
back. For the rental check, `rental()` of `page.py` on made-up answers of `nvidia-smi` and `docker`: a container
refuses a request, `allow_docker=1` lets it through, ComfyUI's own GPU process is not counted and another one is.
Not run: either on a rig, with real timings, a real Docker rental, or a real ComfyUI's progress messages.

For each chat's own settings and image, the page run on a PC without ComfyUI, on stand-in model and LoRA files, in a
browser: the model, task, numbers, seed and LoRAs set in one chat come back when it is opened again and after a
reload, while the other chats keep theirs; an attached image is back with its size, a request sent with it uses the
rig's copy, **Remove** and deleting the chat delete it from the rig; a new chat starts from what was set and then
keeps its own. Not run: any of it on a rig, or two browsers in the same chat at once.

For the chats and the Outputs view (v0.5), the page run on a PC without ComfyUI, on a made-up history and image files:
the history from before chats opens as General; a new chat, its name from the first prompt, rename, archive and
unarchive, delete (its requests, their files and the image one started from are gone); the outputs listed with their
requests, one and several deleted, paths outside the outputs folder refused; a request without a chat (the Claude
tools) lands in General. Not run: requests that finish in a chat, video previews, and any of it on a rig.

Not yet run: a real model generating (no model has been downloaded and run), the memory each build really needs, the
dashboard stats (no `jq` where it was tested), and anything on a real Hive rig (firewall rules, watchdog).

# ComfyUI-Hive

A Hive OS custom miner that runs [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instead of mining, so a rig
switches between Octa and making images and videos by changing flight sheet. Each rig serves a chat page: pick a model,
type a prompt (and attach an image to animate), and the result comes back on the page to watch and download.

Sister project of [Ollama-Hive](https://github.com/Xefier/Ollama-Hive), and built the same way: NVIDIA only, ComfyUI
runs in the foreground of Hive's miner screen, and no system service is installed, so with another flight sheet active
nothing of it runs or holds GPU memory.

## Flight sheet

One flight sheet for every rig: no model is chosen in it. Host `comfyui-hive-v1.64.tar.gz` somewhere the rigs can
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

**A DOCKER drive that isn't mounted is set up by the miner.** When a drive with the label `DOCKER` is there, formatted
as XFS, but nothing is mounted at `/var/lib/docker`, the miner installs `xfsprogs` if it is missing, adds
`LABEL=DOCKER /var/lib/docker xfs defaults,nofail,quota,prjquota,pquota,gquota 0 0` to `/etc/fstab` (once: a line for
that label that is there already is left as it is) and mounts it. Docker is stopped while the drive comes under its
folder and started again after. It is not done while a Docker container runs, nor for a drive that isn't XFS: the
miner says so and waits, as it does when there is no such drive.

## The page

`http://<rig>:8189/` (the miner log and the Hive dashboard say the link). Open it from any PC or phone on the LAN.

- **Models**, in the menu, is a page of the models that fit this rig's GPU, each in the build that fits it: a 32 GB card gets
  higher-precision builds than a 24 GB one, and a model no build of which fits isn't shown (the page says how many are
  hidden). Each card shows with icons whether it makes video and sound (green when it does, red and crossed out when
  it doesn't), whether it takes LoRAs, and each thing it does (what goes in, an arrow, what comes out: a picture to a
  video for image to video), with its build and its size. Under the icons a card says the largest size the model does well (and the one it does
  best, when smaller) and its frame rate or the sound it makes, and an aperture and a brush say how it makes photoreal
  and stylized pictures: green when good at it, grey when usable, red and crossed out when weak. Filters above the cards show only the installed ones or
  those still to download, those that do a task, or those that make video, make sound or take LoRAs.
- **Nothing is downloaded until you press Download** on a model (or say yes when a Claude session asks, see
  [Claude sessions](#claude-sessions)). It goes into the models folder with a progress bar
  and can be cancelled; a download that was cut off continues where it stopped. Files that two models share are
  downloaded once. **Delete** frees the space again, keeping files another downloaded model still uses.
- **The chat:** pick a downloaded model with the picker beside the tasks (**All models…** at the end of its list opens
  the Models page; a model that isn't downloaded yet is said above the prompt, with Download) and what to make (text to image, image to image, edit image, text to video, image to video), write the
  prompt, and press Generate (or Ctrl+Enter). Size, length and seed can be changed; empty means the model's default
  and a random seed. Requests queue and run one at a time; each shows its progress, then the image or
  video with **Download** and **Open** links, or what went wrong. The history stays on the rig.
- **Progress:** one bar for the whole request, full when it is done: loading the model, every pass of steps (Wan 2.2
  14B and LTX have two) and the decoding and saving after them, with the step over all passes, the pace, the time
  gone and about how long is left. The time left comes from this request's pace and from how long the load and the
  end took in the last request like it (same model and task; same settings for the end), so the first request of a
  kind fills the bar by its steps, says "a rough guess", and has no estimate before its first step. The bar never
  goes back; when a request takes longer than estimated it waits just short of full.
- **Negative prompt:** a model that listens to one has a **Negative prompt** line among its settings, filled with
  the model's own; what you write there is what the picture or video should not have, and an empty line goes back
  to the model's own. Wan 2.2 5B, HunyuanVideo 1.5, SD 1.5, SDXL, Pony and Qwen's image edit have it. The others
  run at a guidance of 1 (Wan 2.2 14B with its 4-step LoRAs, Z-Image Turbo, Qwen's text to image), where a
  negative prompt changes nothing, or guide in a way of their own (LTX, MiniMax): they don't show the line.
- **A prompt put together rather than written:** the **Character** card over the prompt and the **Environment**
  card under it open the prompt builder: a place picked from pictures (a kitchen, a bus stop, a forest) with settings for the time of day,
  the weather, the lights and more, then who is in it, set like a game's character or taken from a preset or a LoRA,
  what they wear, how and where in that place they are, and what they hold. Their parts of the prompt are added by themselves
  around the words you write: who, what happens, where. See
  [Environments](#environments), [Characters](#characters) and [Props](#props).
- **A LoRA's trigger prompt:** beside a slot's strength, **Set trigger prompt** asks once for the words the slot's
  LoRA is called up with and keeps them on the rig with the file; from then on **Add trigger prompt** adds them to the
  end of the prompt (not twice), **Use trigger prompt** makes them the whole prompt in place of what is written
  there, and **Edit** changes or removes them. Every browser sees the same ones; each rig
  keeps its own.
- **A photo as the image:** on a phone or tablet the image box has **take a photo** beside "choose a file": it
  opens the camera, and the picture taken is attached.
- **A request again:** **Use again** under a request puts its prompt, model, task, numbers, seed, LoRAs and image
  back in the composer with a new seed; the same arrows with an S inside them, beside it, bring it back with its
  seed, for the same result again. **Use as input** under an image the rig made attaches it,
  switching to the model's task that starts from an image. Each request shows the size and numbers it was made with.
- **A video continued:** **Continue**, under a video beside Download, does the same as Use again but starts
  from the last frame of that video, with a new seed: to go on where it ended. The request made this way is a video of
  its own; with **Also make one stitched video of them in a row** ticked (it is, until you untick it), the rig also makes one video of the whole
  row when it is done: every video continued up to this one, one after another, the frame they share left out once,
  with their sound. It is made from the videos themselves each time, never from an earlier stitched one, with PyAV,
  which ComfyUI has installed. The chat shows only the stitched video under such a request: the part it added is in
  it, stays on the rig for the next stitching, and is listed in Outputs. **play what this one added**, above it, opens
  it large from where that part starts, and **Skip to the last part** in the large player jumps there; a click on the
  video plays it from the start. **Delete** under it deletes the stitched video together with the part this request
  added (the videos before it stay). The last frame is taken as the browser plays the video, so a little softer than the
  model made it.
- **Use again on a continued request** continues the same video again: from the same moment (its end, or the second it
  was continued from), with the frame it started from then, and stitched with it when done if it was. Clear the
  seed for another result of the same step.
- **Continued from a moment before the end:** the row over the image, *Continues that video from … s*, takes the
  second to go on from (empty: the last frame), and shows the video's length. Or open the video large, pause it at
  the moment, and click **Continue from here** under it. The image becomes the frame shown at that second, and a
  stitched video has the continued one up to that frame only. Continue from here on a stitched video finds the
  request whose part that moment is in (one stitched before this was added can only be continued from its end).
- **A video that ends early:** when the end of a video is bad and the rest is good, open it large, pause it at the
  last good moment and click **End here**. The video then plays to there and starts over, shows *Ends at … s* under
  it, and what is made from it takes it to there: Continue starts from that frame, Add sound makes sound for that
  length, and Download and Open hand out a file cut there. The file itself stays whole, so End here at another
  moment moves the end and **No end** removes it. **Cut for good**, after an *Are you sure?*, cuts the file itself
  there: what came after is deleted and can't be brought back.
- **A request taken to another rig:** with **Other rigs** on, a list of the rigs stands beside Use again (Continue goes by it too),
  set to the open chat's own. With another rig chosen, they start a new chat on that rig, named after this one, with
  the request's prompt, settings and the image it started from (for Continue, the video's last frame). A LoRA that rig
  doesn't have is left out and said; a model it doesn't offer leaves the prompt and image for another model. A video
  continued on another rig isn't stitched with this one: each rig only has its own files.
- **What Generate keeps:** the icon on Generate's right opens a list of what the composer keeps after it: **New prompt** (the
  prompt, Repeat and the video continued are cleared), **Use again** (everything stays but the seed), **Use again with seed**
  (an empty seed becomes the one the request was made with) and **Continue** (after a request of one video, the next goes on
  from it, so each Generate adds the next part). Each browser keeps its own; the timeline's composer and the frame dialog keep
  Generate alone.
- **The swipe viewer:** an output opened large swipes left for a thumbs down (Undo brings it back), right for a thumbs up, up
  for a sheet with the request's details and links, down to close, a double tap for full screen on a phone, the sides to step.
  **Rate**, beside the chat's filters and in Outputs, goes through what is new, then everything unrated. At the end of a pile of
  attempts (Edit image's, a gap made with Repeat) **Try again?** is a card of its own, answered by a thumbs up (another attempt, with
  a new seed) or a thumbs down (no); a thumbs down on every attempt no longer makes another by itself.
- **Show chips:** the chat's Show chips also have **Images** and **Videos**, each chat keeping its own choice. A request folded
  to one line has Delete, as the one under the request does.
- **Keep colours:** on unless a request turns it off, among the numbers of Edit image, Image to image and First and last frame:
  what a model made from a picture is brought back to that picture's colours once the model is done, since each gives it back a
  little brighter and warmer; the request says what was taken out. **Match colours** under an image makes a copy of it in the
  colours of another picture you pick, as a request of its own.
- **A request and what it made, as a pair:** in the chat they are framed together with a rail down the left. Its grip
  moves the pair to another chat of the rig (dragged onto one in the list, or clicked or tapped for a list of the chats
  and a new one, which is the way on a phone), and the arrow under it folds the pair to one line (its prompt, small
  pictures of what it made, how it ended), kept by the browser.
- **Changing an image, editing a video:** an image in the chat has **Change…** (a pencil) beside Use as input, which opens the
  frame dialog on that picture, so it is changed with a model, LoRAs and a prompt set there while the composer is left as
  it is; each picture made is kept in the chat and the outputs. **Edit video** (was Crop) under a video, in the chat, the
  Outputs view and the viewer, is a dialog that trims, crops and turns it, and makes a video of its own as a request in the chat.
- **Stitch afterwards:** a done video that continues another and wasn't stitched with it has **Stitch with the videos before it**
  under it, which makes the row's stitched video in the background.
- **Picking another model** takes out the LoRA rows that have no files for it, and says which; a scene character's row comes
  back by itself when a model it has files for is picked again.
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
  links staying, until **Show**; a thumbs down hides it too. **Favorites** and **Liked**, in the menu (☰) and as tabs of
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
- **Finished, until looked at:** when a chat's request ends, its card in the list gets an icon beside its name,
  **finished** (a tick in a circle with a dot, green) or **failed** (an X in place of the tick, red), which goes away when the chat is opened. The open chat gets none, unless it ended while
  the browser's tab was in the background. Each browser keeps its own account of what was looked at, which its tabs
  share (a chat opened in one loses its mark in the others), and only what
  ends after a chat was first seen there is marked.
- **One scroll bar:** on a desktop screen the page itself doesn't scroll, only the chat's messages do (and the side
  panel when its lists are longer than the window). A phone scrolls as one page.
- **On a phone:** the page opens on the list of chats; a chat opens as a screen of its own, with an arrow (or the
  phone's Back) to return to the list, and Models is a page reached from the menu.
- **The top row:** Comfy's mark and the worker's name, which has the row to itself (the page's title is no longer
  written there), with an arrow that opens the rig's state: VRAM, GPU load, RAM
  and disk as bars, the GPU, ComfyUI and the version. Folded to begin with, and a rig that doesn't answer, has no GPU
  or may be rented still shows. The gear at the top right holds the settings (Other rigs, Sound when done, Thumbnails, updates,
  Account) and the menu (☰) beside it the places to go (Models, LoRAs, Scene library, Outputs, the miner log, the
  ComfyUI editor, …); they and the eye stay in their corner when the page scrolls. **+** starts a chat,
  with a choice of the rig when Other rigs is on.
- **A request repeated:** **Repeat** beside Generate makes the request that many times (20 at most). As it is, they
  are separate tries of the prompt, each with a seed of its own, all queued at once. For a video, with **Each
  continues the one before** ticked, they are a row: each starts from the last frame of the one before, which the rig
  takes from the video itself, so the row goes on with the page closed. With the stitched video ticked too, each one
  from the second on also gives the stitched video of the row so far. Only the one being made is queued, the next
  when it is done: one that fails or is stopped ends the row.
- **Continue on a video still being made:** a request being made or waiting has **Continue** too, beside Stop or
  Cancel. It brings its prompt and settings back the same way, and Generate queues the next one at once: it waits for
  that video and starts from its last frame once it is done (the rig or hub takes the frame, not the browser). If that
  video fails or is stopped, the one waiting for it fails too. Until then the start frame's box shows that frame to
  come, with the video's progress bar. **Same as start** on the end frame makes the end frame that frame too, for a
  video that ends where it starts.
- **A sequence of prompts:** **+ Next prompt** over the prompt (for a video, with a model that can start one from an
  image) makes the request a sequence: a row as above, but each video with a prompt, LoRAs and length of its own. A
  tab for each prompt shows it in the composer; tabs are dragged (or moved with Alt+← / Alt+→) to change the order,
  and × removes one. The first is made as the composer is set, with its task, start frame and the scene's text; each
  later one is made with the model's image to video task from the last frame of the one before, so it has no frames
  or Environment and Character of its own, and its LoRAs are checked against that task. The model, the size and
  steps, the place and the characters, and a character's LoRA (shown on prompt 1, every prompt's) are the
  sequence's. A sequence is made once, so Repeat is hidden while there is one (and + Next prompt while Repeat is more
  than 1); the stitched video works as for a row. It stays in the composer after Generate, kept with the chat.
- **Templates:** **Save template** beside Generate keeps what the composer has under a name, with a tick for each part:
  the model and task, the numbers (size, steps), the video length apart from them, the seed (unticked at first), the prompt, the LoRAs (not a character's), the
  place, and the characters with their LoRAs (unticked at first in a sequence). Of a sequence it keeps every prompt,
  with its LoRAs and length, but never a start or end frame. **Use template** lists them: one fills in only what it
  keeps and leaves the rest as it is, a sequence's builds the sequence again, and one of a single prompt fills the
  prompt shown of a sequence. A model or LoRA that isn't here is said. Each account has its own, on the page's own
  rig or hub (`templates.py`).
- **A rental is never interrupted by a request:** before a request is taken, and again before one that waited in the
  queue starts, the rig checks what it checks before starting ComfyUI: a GPU process that isn't ComfyUI, or a running
  Docker container (unless `allow_docker=1`). If there is one, the request is refused with what was found and nothing
  starts. This holds for the Claude Code tools too. The page shows a warning above the chat and turns Generate off
  within about ten seconds of one being found.
- **Chats:** the requests are kept in chats, listed in the side under **Chats**, which folds its list away with the
  arrow beside it (and so does **Timelines** below it, the timeline projects). **New chat** starts one; it is named after its
  first prompt until you **Rename** it (the pencil beside its name). A card's Rename, Archive (an eye crossed out) and
  Delete (a trash can) are icons on its own row: on the card pointed at, the open one, and always on a phone. Click a chat to open it; which chat is open is each browser's own, so a PC and
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
- **The image for image to video, image to image or to edit:** drop it on the chat, paste it (Ctrl+V, from a screenshot or a copied image), or
  choose a file. A preview shows it with its size; it stays attached across task and model switches until **Remove**.
  Pasting or dropping an image while on a text task switches to the model's task that starts from one (image to
  video, image to image for SDXL, Pony, SD 1.5 and Z-Image, or edit image for Qwen-Image). Images other than
  PNG, JPEG and WebP are turned into PNG first. Two buttons fit the video's size to the image:
  - **Use image size**: the image's own width and height, so the video starts from the exact image. A bigger image
    than the model takes is scaled down to fit, keeping its shape.
  - **Match aspect ratio**: the image's shape at the current resolution, keeping the shorter side of the size set now.
    Video models are made for a class of size named by that side (480p, 720p), which the time and memory follow, so
    1280 × 720 with a portrait image becomes 720 × 1280.

  Either way each side is rounded to the model's multiple, and the page says when it scaled or rounded. MiniMax H3's
  image-to-video, Qwen-Image's editing and image to image take their size from the image by themselves, so they have neither button.
- **The end frame:** a model that can end a video on a given picture (Wan 2.2 14B, LTX-2.5 and MiniMax H3) has the task
  *First and last frame*, with an end frame beside the start frame: side by side where there is room, the start on the
  left, one over the other on a phone. In *Image to video* on such a model a **+ End frame** box switches to it. The
  end frame may be left out (the video then ends where the model takes it) and does what the start frame does: drop,
  paste, choose a file or take a photo, **Remove**, kept in the chat on the rig, back with **Use again**, and **Use as
  end frame** under an image of the chat. An image dropped on its box goes there, anywhere else to the start frame; a
  pasted one goes to the box last clicked or filled. **Swap with start** swaps the two, and the end frame's size says
  when it isn't the video's shape. In a row (*Each continues the one before*) only the last video ends on it.
- **Edit image** (Qwen-Image 2.1 Turbo): attach the image and say in the prompt what to change ("make it night",
  "replace the car with a bicycle", "remove the text"); the result keeps the image's size. A prompt-refining model
  first turns the instruction into a fuller one, as in ComfyUI's own template. MOSS-Image edits the same way, with
  the instruction used as written and the image kept at its own size when that is between 0.25 and 4 megapixels
  (scaled into that range otherwise).
- **Image to image** (SDXL 1.0, Pony Diffusion V6 XL, SD 1.5 and Z-Image Turbo): attach a picture and describe in the
  prompt the whole picture to make of it ("a watercolour of a red cottage in a meadow"), not the change. It is scaled
  to the model's size in its own shape (about 1 megapixel, a quarter of that for SD 1.5) and redrawn. **Strength**
  (0.05 to 1) says how much of it is made anew: low keeps it and changes the style and detail, high keeps only its
  layout and colours. It starts at 0.6, and at 0.8 for Z-Image Turbo, which changes less at the same strength. The
  negative prompt, steps, CFG and LoRAs are those of text to image.
  **Mask…** beside **Crop** opens a dialog to paint the part of the picture to make anew, with a brush, an eraser and
  **Smart select**, which picks out the thing clicked (Segment Anything, run in the browser and fetched once from the
  internet), and a soft edge that blends it in. Only the masked part changes; the rest stays to the pixel. The mask is
  sent with the request and **Use again** brings it back with the image.
- **LoRAs:** Wan 2.2 (14B and 5B), HunyuanVideo 1.5, LTX-2.5, MiniMax H3 (its videos), Z-Image Turbo, SDXL 1.0, Pony Diffusion V6 XL and SD 1.5 take up to 8 of your own LoRAs per request, in **LoRAs**
  under the task buttons: each slot is a file, picked from a pop-up over its row (the ones for the model picked, those with a picture as tiles and the rest as a list, with a search of their names and trigger prompts), and a strength (1 by default, negative allowed), set with the slider (-10 to 10, for slider LoRAs
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
  - **Turning an image:** the start frame and the end frame each have **Turn** once an image is attached: a slider
    and a number, by any angle either way, and **Level** to go back. It is the clip cutter's turn: what is kept is
    the largest level part of the image's own shape that the turned image holds (the whole of one turned onto its
    side), turned each time from the image as it was attached. The turned image is the one the chat keeps and the
    request starts from.
  - **Changing a frame:** a video's start or end frame has **Change…** beside it (**Make…** while it has none, or
    **Make from the start frame…** for an end frame), which opens the chat's composer in a dialog with only the image
    models and tasks that make or change a picture. Each picture previewed there goes into the frame at once, and **Back
    to the original** undoes it. The dialog's model, prompt and LoRAs are kept with the chat, apart from the video's. A
    model that is given a size makes the frame at the video's size, or as near to it as it makes in the same shape. While
    it paints over a picture, the scene builder writes what was changed as instructions, and warns of changes only an
    edit makes, with **Use Edit image** beside it. A video continued from a frame that was changed is sent as a cut. A
    gap of the timeline can start or end on a changed frame the same way, in the fill panel. So a character whose LoRA is
    for an image model can be in a video of a model the LoRA has no files for.
  - **Motion and detail:** Wan 2.2 14B is two models, one for the first steps of a video, which settle the layout,
    the shapes and the motion (its high-noise part), and one for the later steps, which draw the faces, the textures
    and the likeness (its low-noise part). A LoRA's row has a strength for each there, **Motion** and **Detail**,
    both the same until one is moved; at 0 the LoRA isn't put into that part at all. So a LoRA of a motion can be
    kept out of the detail, and a LoRA of somebody out of the motion, where the two get in each other's way. Under
    **LoRAs** the two files are the **Motion file** and the **Detail file**.
  - **The two halves of a pair:** which half a file is, is told by its name: `high` or `low` as a word
    (`..._high_noise`, `...-LOW-v1`), run together with noise (`highnoise`, `HighNoise`), or as a word of a name in
    capitals (`BounceHighWan2_2`); and two files that differ in nothing but `H` and `L` (or `HN` and `LN`) as a word
    are a pair too. Files added, and versions downloaded from Civitai, are paired by it. **Pair split halves** under
    **LoRAs** looks for what was left as two LoRAs, one of each half, for the same model and task: by their files'
    names, by the page they both came from, or by their own names. It says what it found and puts each two together
    when you agree.
  - **Those for the task:** the chat's list of LoRAs has those for the task picked. One whose files for the model
    are said to be for another of its tasks (image to video, while text to video is picked) is left out; **Other
    tasks** over the list brings those in for that once. A LoRA for image to video is listed for a video from a first
    and a last frame too.
  - **Categories:** a LoRA is a character (somebody), a slider, clothing, or none of these: **Category** under
    **LoRAs** says it, and in the search of Civitai's window before a download. Not said, it is told by itself: a
    slider by "slider" in its name or its file's, clothing by "outfit", "clothing" or "clothes" there. The chat's list
    of LoRAs has a switch for each category over it, to show only the sliders or all but them, kept in the browser;
    the **LoRAs** page lists its categories down the left (All first), and a click lists the LoRAs of one. In the scene builder the sliders are the Character step's
    **Sliders** section (after Basics, Body, Face, Hair and Details, with how many are set), each with a slider of its
    own (0: not used) and its reset (the circular arrow) while it is off 0, and **Reset all** over them; the clothing LoRAs lead the Outfit step, put
    on and taken off with a click; a character's are among the request's LoRAs, pinned, at the strength set there,
    and what it wears of them adds its trigger prompt to the character's part of the prompt. A preset keeps its
    sliders, and its clothing LoRAs with what it wears. You can have categories of your own besides: **+ New category**, last in the
    list at the left (or at the foot of a LoRA's own Category list), makes one by a name; its pencil renames it and its
    LoRAs stay in it, and × takes it away. A LoRA dragged by its grip onto a category is put in it. From then on it is
    among the others on every LoRA, in the page's list and over the chat's list. Each account has its own. A LoRA of a category that is taken away is of
    none, and told by itself again.
  - **Style:** a character LoRA's card has a **Style** beside its Category, Realistic or Stylized, the same style the
    Character step lists it by (see Characters).
  - **The character first:** a LoRA of somebody is a character preset (**Character preset** under **LoRAs**, or in
    the search of Civitai's window before it is downloaded). In a request made from words alone (text to video, text
    to image), where one is for the model picked, the LoRAs' rows start with the **Character**'s, whose list has
    those only, and the rows under it are **Modifier**s, whose list has the others. Elsewhere every row lists all. A
    character of the scene builder that is made with a LoRA has that LoRA's row among the request's from the moment
    it is in the scene, and the row is pinned: it can't be removed or given another LoRA until the character is taken
    out of the scene or its LoRA off the character, and a character given another LoRA or preset, or taken out, takes the rows it pinned (its LoRA, sliders, clothing, a prop's) with it.
  - **Recommended LoRAs:** a LoRA's card has recommended ones (a chip of each, with the strength it is added at; ⇄ makes them
    list each other). When it is on a request, the chat offers those not on it yet that have files for the model picked, added with
    one click or all at once; × stops offering them in that chat.
  - **A range for the detail part:** with **Motion / Detail** ticked, the detail (low-noise) part gets its own Min, Max and Default,
    and the chat's Detail slider keeps to them.
  - **Several trigger prompts:** under **LoRAs**, **+ Trigger prompt** gives a LoRA one more (another pose, outfit or
    way to call it up), each with a name. In the chat, a LoRA with several has **Trigger prompts** on its row: a list
    of them by name, with a search, where a click adds one to the prompt and **Use** makes it the whole prompt. No two of a LoRA's say the same (whatever
    their capitals, spaces and commas): one written a second time is not kept. The
    first is the LoRA's trigger prompt wherever only one is meant (the scene builder's characters, a training).
  - **Marking and finding them:** under **LoRAs** each LoRA has the star and the thumbs an output has. A mark hides
    nothing: the LoRAs are listed by it there and in the chat's picker, the favorites first, then the good ones, the
    unmarked, and the bad ones last. The row over them lists only those with some words in their name or trigger
    prompt, with files for one model or for one task (text to video, image to video and so on), the
    characters or the others, or with one mark.
  - **Which model a LoRA is for:** a LoRA works only on the family it was trained for, which its Civitai page gives
    as the base model: "SD 1.5" for SD 1.5, "SDXL 1.0" for SDXL, "Pony" for Pony Diffusion V6 XL, "Wan Video" for Wan
    (a Wan 2.1 14B LoRA works on Wan 2.2 14B too), "HunyuanVideo" for HunyuanVideo. One for another family
    fails no request: ComfyUI finds nothing it fits and it simply changes nothing. Pony and SDXL LoRAs load on each
    other's model but work poorly there.
  - **Finding one on Civitai:** under **LoRAs**, **Find on Civitai** opens a search of civitai.com or civitai.red
    (picked at its top), by words, by model (only LoRAs for a model of the catalog are listed: each model's `civitai`
    in `tools/catalog-src.json` names the site's base models it stands for), by order and period, with the site's own
    pictures as tiles; **Found LoRAs** in the gear's panel sets how wide they are, and **Mature** whether the pictures
    the site marks so are hidden (LoRAs marked so aren't listed then), blurred or shown. A picture's mark in its left
    corner shows it large, with the LoRA's other pictures to go through; a video's mark in the right corner plays it
    there, one at a time, with its sound unless **Sound** at the window's top is off. A LoRA picked shows its
    versions, one for each model it was trained for: every one ticked is downloaded and the LoRA made here has files
    for each of those models, a high-noise and a low-noise version or file as one pair. Any of them can be ticked together: a LoRA has one
    version's files for a model, so a further version for the same model becomes a LoRA of its own, named after its
    version too. Its picture is one of the
    site's, chosen there; **a button in the corner of an example picture** makes it the LoRA's picture. Its trigger prompt starts as the site's trigger words for the versions ticked; the prompts
    its example pictures were made with, what its text seems to give as a prompt, and its lines on strength and
    settings are offered beside it to add or use, since everybody writes those their own way. Where the site has no trigger words for the versions ticked, the box
    starts with another version's, or else with what the LoRA's text seems to give as one, and says so under it. A
    LoRA made this way has a link to its page on the site under **LoRAs**, and while it has no trigger prompt,
    **Get its trigger prompt** there looks for one on that page the same way. With **Keep its example prompts**
    ticked in the search's window, as it is to begin with, the prompts the versions' example pictures were made with
    become further trigger prompts of the LoRA, "Example 1", "Example 2" and so on, after its own, which is then
    called "Trigger words"; **Get its example prompts** under **LoRAs** does the same for one made earlier. Each example keeps the picture it
    made, shown small beside it under **LoRAs** (a click shows it large) and in the chat's list; the pictures stay on
    the site and are loaded from there. A LoRA whose file there is a zip (the Diffusers format) can be downloaded too: the one `.safetensors` inside is taken out under the zip's name, and a zip of several, or of only a `.bin`, is refused with what it holds. The search needs no
    account; a download needs a Civitai API key (made on the site under Account settings, API keys), which an admin
    gives in that window and which is kept in the data folder as `civitai_key` (or `CIVITAI_TOKEN` in the
    environment). Versions in early access, and files that aren't `.safetensors`, can't be downloaded. The rig or
    hub asks the site, not the browser, which only loads the pictures (`lorasearch.py`, `lorasearch.js`).
  - **Adding one:** drop a `.safetensors` file on the chat or choose it in the LoRAs box; it uploads into the rig's
    `models/loras` folder with a progress bar and can be cancelled. 8 GB at most each, `.safetensors` only, and
    the name keeps only letters, digits, spaces and `. _ - + ( )`. A file copied into that folder by hand (in a
    subfolder too) is listed as well. **Delete** removes one, unless a waiting or running request uses it.
  - They are apart from the models' Download and Delete: deleting a model never removes one of your LoRAs, and the
    LoRAs a model brings aren't in this list.
- **Switching model** is picking another card. The rig lets go of the last model's memory first, so the first request
  on a new model takes longer while it loads.
- The page also links ComfyUI's own editor, for building or changing workflows by hand, and shows
  the end of the miner log. The editor is also a view of the page, at `/comfy/` (on a hub, a worker's at
  `/rig/<worker>/comfy/`, from the worker's card): it asks for the page's login, so ComfyUI's own port can stay closed.
  With accounts it is for an admin only, and another rig's opens only once that rig has shown it has the hive's key.

### Accounts

Without accounts the page and ComfyUI have no login: like Ollama-Hive's API, anything on the LAN that can reach them
can use them, including starting a download, deleting a model, a chat or an output, and uploading or deleting a LoRA.
They listen only on the private LAN address, and `allow=` limits which addresses can connect.

With accounts, the page answers only who is logged in:

- **Make yours** in the gear, under **Account**. The first account is the **admin**'s, and everything there is at that
  moment becomes its own: nothing is moved or rewritten, what has no owner is simply the first admin's. A browser logs
  in once with the name and the password and stays logged in for a year; **Log out** is in the same box.
- **An admin** may do everything, and adds the other accounts there, each **an admin**'s or **a user**'s, gives one
  another password (which logs it out everywhere), makes a user an admin or back, and deletes one. What a deleted
  account made stays, and is the first admin's from then on.
- **A user** has only their own things: chats and their requests, outputs, LoRAs, folders of chats and timelines.
  Nobody else's are listed or can be opened, changed, deleted or used in a request, and two accounts can each have a
  LoRA of the same name. A user can't download or delete models, or touch the token, updates, clean-up, the log or the
  accounts.
- **Looking at an account:** an admin's own lists show only their own things too. **Look**, beside an account, shows
  the page as that account has it, with a bar at the top that says so and **Back to my own**. What is made meanwhile
  is that account's.
- **Your own password** is changed in the same box, with the one of now. Every other browser of the account is logged
  out by that.
- **What is kept:** for each account a salted hash of its password in `accounts.json` of the page's data folder, never
  the password; and a random key in `hive_key.json`, made with the first account, that sessions are signed with. Keep a copy of the hub's `hive_key.json` and `accounts.json`: a rig that loses the key it was given makes none of its own and is open again, for its hub to lock with one press.
- **Forgotten:** put a new password into a file `password.txt` in the page's data folder (`<data_dir>/page`) and start
  the miner again. It becomes the first admin's and the file is deleted. Where there is no account yet, one named
  `admin` is made with it.
- **Taking the lock off:** in the same box, for the one account that is left (delete the others first), with its
  password. There are no accounts then, and everything on the network can use the page again.
- **ComfyUI's own port** (8188) can ask nobody to log in. On a rig whose page does (it has accounts, or a
  `password.txt` to make one of), ComfyUI listens only on the rig itself from the miner's next start, and the page no
  longer links its editor. Until that start the page says that the port is still open.
- **The Claude Code tools** log in too, as an account of their own if you make one: `comfyui-hive login` (see Claude
  sessions).
- **Wrong passwords:** after five from one address, that address waits a minute. The log names the address.
- **What it doesn't do:** the page is plain http, so the accounts keep out what can reach the port, not what can read
  the network's traffic. For the page from outside the LAN, use a VPN into the LAN (WireGuard on the router, for one),
  never a forwarded port.
- On a hub the accounts are the whole hive's and its workers take them from the hub; that is the hub's own side.

With or without accounts, a request that a page of another site has a browser send is refused: a website open on a
PC or phone of the LAN can't work the page behind your back.

## Room on the data drive

A hub's Workers page has **Clean up** on each worker's card: what can go from the rig's data drive, each with how much
it frees. Everything there can be had again. Files the hub has too, what requests started from, temporary files, the
installers' cache, models that programs fetched by themselves, LatentSync and Chatterbox, the training files, and
Docker's unused images, build cache and stopped containers. Docker is only cleaned while the rig isn't rented (no
container runs and nothing else has the GPU), and never its volumes.

## Updates

The miner updates itself, so the flight sheet's installation URL never has to change again: any release from v1.0 on
keeps itself at the newest one. About every quarter of an hour, and once before it starts, it asks GitHub for this
repository's newest release; a newer one is downloaded, the miner's folder is replaced by it (Hive's config for the
miner is kept), and the miner starts again as the same process, which takes about as long as a switch of flight sheet.

- **Update automatically**, under the gear, is on until you turn it off: the update is taken by itself.
- With it off, the gear says which version is available and offers **Update**.
- Either way it waits until nothing is being made or downloaded and the rig isn't rented, and says what it waits for.
- A release that can't be downloaded or isn't whole changes nothing: the miner keeps running as it is and says why.
- **v1.0 to v1.4 could not be stopped after an update:** the miner an update started ignored the signals Hive stops a
  miner with, so a miner restart, a switch of flight sheet or a rental's start left it running with ComfyUI on the
  GPU, and a restart put a second one beside it (each then took the other's ComfyUI for a rental). v1.5 starts
  without that, sets itself right when it was started so, and stops any older run of itself when it starts. A rig
  that shows a rental it doesn't have, or two ComfyUIs, needs one reboot to be rid of the old run.

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
| `comfyui-hive login` | When the page has accounts: asks for an account's name and password, and keeps the session a rig gives for them (never the password itself), good for a year. The tools then work as that account: what they make is its own, and they see only its things. Run it again after that account's password changes |
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
| Wan 2.2 14B | text/image to video, 16 fps | fp8 | fp8 | 64 GB | Both experts and the 4-step speed-up LoRAs, for both tasks, each half's strength and steps settable. Up to 5 seconds (81 frames). Takes your LoRAs |
| Wan 2.2 5B | text/image to video, 720p 24 fps | fp16 | fp16 | 17 GB | Takes your LoRAs |
| HunyuanVideo 1.5 | text/image to video, 720p 24 fps | fp16 run as fp8 | fp16 | 43 GB | Takes your LoRAs |
| LTX-2.5 | text/image to video with sound | not offered | int8 | 42 GB | Gated: accept the license at [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) and give the account's token. Free for organisations under $10M yearly revenue. Takes your LoRAs |
| MiniMax H3 | text/image to video with sound, text to image | pruned w6a8 | pruned int8 | 39 / 44 GB | Commercial use of what it makes needs a MiniMax license (sold through Comfy). Its videos take your LoRAs |
| Z-Image Turbo | text to image; image to image | bf16 | bf16 | 19 GB | Takes your LoRAs |
| Z-Image Base | text to image | bf16 | bf16 | 19 GB | 25 steps at CFG 4, with a negative prompt. Takes your LoRAs, those of Z-Image Base and not Turbo |
| Qwen-Image 2.1 Turbo | text to image, up to 2K; edit image | int8 | bf16 | 34 / 40 GB | Editing has its own prompt-refining text encoder, included in the download |
| MOSS-Image | text to image, 0.25 to 4 megapixels; edit image | bf16 | bf16 | 17 GB | The SFT model. It likes a long, detailed prompt: **Enhance prompt** (off unless you turn it on) has its text encoder rewrite a short one into that first, as ComfyUI's template does, which takes longer. Good at English and Chinese text in the image. The page also sets the steps and CFG. An int8 build (12 GB) for cards under 16 GB. Editing is its edit LoRA, included in the download. Takes your LoRAs |
| SDXL 1.0 | text to image, 1024 px; image to image | fp16 | fp16 | 6.5 GB | Stability's base model. Takes your LoRAs (SDXL) |
| Pony Diffusion V6 XL | text to image, 1024 px; image to image | fp16 | fp16 | 6.5 GB | SDXL-based, prompted with tags: start with `score_9, score_8_up, score_7_up`. Clip skip 2 and Euler a, as its author advises. Takes your LoRAs (Pony) |
| SD 1.5 | text to image, 512 px; image to image | fp16 | fp16 | 2 GB | Takes your LoRAs (SD 1.5) |
| MMAudio | sound for a video, 44.1 kHz | fp16 | fp16 | 5 GB | Needs its node pack, which the miner installs. Weights for non-commercial use |
| HunyuanVideo-Foley | sound for a video, 48 kHz | fp16 | fp16 | 11 GB | Needs its node pack; fetches two encoders (2.3 GB) on first use. An fp8 build (6 GB) for cards under 16 GB |

SDXL, Pony and SD 1.5 share ComfyUI's SDXL template (one checkpoint, prompt, sampler, decode), with the page also
setting the steps and CFG and a fixed negative prompt per model. The workflows are ComfyUI's own templates for each model, as its editor offers them (with their defaults: speed-up LoRAs
on, sizes, lengths); only the prompt, image, size, length and seed are set by the page, and your LoRAs added. **Which build fits which card is
an estimate** from the files' sizes and the templates' own notes (the Wan 2.2 template measured its fp8 build at 84% of
a 24 GB card), not yet measured on these rigs. If a model runs out of memory on a card, raise its `min_vram_gb` in
`tools/catalog-src.json` and build again.

## Environments

**Environment**, the card under the prompt, opens the prompt builder at its first step (its steps are along the top:
Environment, Character, Outfit, Pose and place, Props, and the prompt at the right is what the open step writes). For a video that starts from an attached image, the builder greys out what the image already shows (the place, who they are, what they wear, where they are, how they are framed) and writes only what moves; before an image is attached everything is offered. The
step is a picker of places: 113 of them, as tiles with a picture each, under Home, Office and work, Transport, City
and street, Food and shops, Public places, Leisure and Nature. **Indoors** and **Outdoors**
narrow the tiles, and the search finds a place by its name. A place picked has its settings beside it, and under them
the prompt they make, written anew with every change:

- **Time and weather:** the time of day, the season, the weather (rain, fog and snow with a slider for how much), the
  wind and the temperature. Indoors they are what the windows show, and a place no daylight reaches (a basement, a
  subway station) has none of them. Wind and temperature are outdoors only, and the temperature says only what a
  camera sees of it: frost and breath, or heat haze.
- **Snow and the temperature** can't contradict each other, and the one touched last stays: the slider moved to
  Freezing turns rain into snow, and to Warm turns snow into rain; Snow picked while it is hot puts the temperature
  back to mild, and Rain picked while it is freezing makes it cold. The line under the settings says what gave way.
- **Light:** the lights that are on (lamps, fluorescent tubes, candles, neon; street lamps or floodlights outdoors),
  how bright, and their colour from a colour picker. The prompt names the colour ("a deep blue", "a warm white"): a
  model doesn't read a colour's number.
- **Condition:** clean to dirty and new to run-down, two sliders, since a spotless place can be derelict and a new one
  filthy. From Messy on, the prompt also says what that place has lying about (a kitchen: dishes piled in the sink).
  Wealth, from poor to luxurious, and for a room its decor (modern, rustic, industrial, ...).
- **Where and when:** the country, which the buildings, fittings and signs follow (or the land, for a landscape), and
  the period, from medieval to the far future.
- **People and mood:** nobody, a few, busy or packed, and the mood (cozy, eerie, sterile, ...).
- **Picture:** where it is seen from (a wide shot, a low angle, through the doorway, from the air), the look (a
  photograph, a film still, anime, a watercolour, ...), and how much of the place is described (**Detail**: 3, 6 or
  all 8 of the things it has). For a video task, also how the camera moves, and the prompt ends with what keeps
  moving: the rain, the view from a train's windows.

Every setting starts at saying nothing, and a setting that says nothing adds no words: the prompt is the place alone
until something is set. A landscape has no decor, wear or period, and a setting that means nothing for the place
picked isn't shown.

**Written as** the model picked in the chat reads best: sentences for the models that read a description, tags for
those trained on them (SD 1.5, SDXL and Pony: `"prompt_style": "tags"` in the catalog), or as chosen there.

**The prompt is put together by itself.** What the builder writes never goes in the prompt box: the box holds your
own words, and a request is sent with the characters' part before them and the place's part after them, in that
order: who, what happens, where. A later prompt of a sequence starts from the last frame of the one before, which
shows them already: its words go alone.

The two parts are **cards** of the composer, the Character card over the prompt and the Environment card under it. A
click on a card shows its part of the prompt (locked: it changes only with the settings), and the pencil beside it
opens the builder there. With nothing picked, the card is **Add a character** or **Add an environment**.

**Words of your own** can go **before** and **after** a part, under the builder's settings: the place has a pair, and
so does each character. **Done** closes the builder; **Copy** takes every part elsewhere. The chat keeps the place,
the characters and your words with its other settings, on the rig. A character preset keeps its character's
words too, and a chat's character of that preset has them as the preset has them now, until the chat changes them for itself. **Reset all** forgets the place and the
characters; **Reset** puts back what the open step sets, and nothing of the other steps.

**The pictures** are made once, by an admin: the bar under the places says how many have one, and **Make the …
missing** makes the rest with the text-to-image model chosen beside it (Z-Image Turbo when it is there): only those
without a picture, never one that has one. Each is asked at the size it is shown at (512 × 288 for a place, 384 × 384
for a prop or a garment, 336 × 448 for a pose, or the nearest the model takes) and is a request of its own, a few at a
time, in the background: the hub, or a rig on its own, gives out every other request waiting first, so a chat's
request doesn't wait behind them. They are made in a working chat that isn't listed and is deleted with its files at
the end, and the rig or hub keeps each in its data folder (`environment_pictures`). The page has to stay open
meanwhile: loaded again, it goes on where it was. **Stop** sends no more and cancels those sent and not done yet, with
what was made kept. The [Scene library](#scene-library) has the same bar on its Places and Props tabs, one tab at a
time. **Make its picture again** and **Remove its picture**, under a place's
picture, are for one place. A place without a picture shows its first letter. The Outfit step's garments and the
Pose step's poses get their pictures the same way, each from the bar under its own step: a garment as a product
photograph, a pose as a grey mannequin.

One set of pictures serves every model: a picture says which place a tile is, not what a model would make of the
prompt, and a set for each model would be a hundred requests per model, minutes each for the video models. They are
the hive's, not an account's: every account sees them, and only an admin makes or removes one.

The places and every word a setting adds are in `comfyui-hive/environments.json`, which says how it is laid out:
a place is added there, as a name, what the scene shows, what a dirty one has lying about and where in it somebody
can be; an option of a setting with its sentence for indoors and outdoors, and its tags.

## Props

**Props**, the builder's step after Pose and place, are things in the picture: in a character's hands or about the
place. A prop is described once, by the words the prompt says of it, so the words you write in the composer can
just say "she picks up the broom" and the model knows which broom.

- **The built-in props** (115, from Everyday and Food and drink to Tools and work, Sport and play and Fantasy and
  costume) are everybody's. Their pictures are made once by an admin, like the garments', with the bar under them, or one at a
  time with **Make its picture** beside a prop (also **Make its picture again** and **Remove its picture**).
- **Your own props** are your account's: **+ New prop**, or **Make your own from it** on a built-in one. A prop of
  your own has a name, what the prompt says of it with every detail, optionally one of your LoRAs it is made with
  (it is among the request's LoRA rows while the prop is in the scene), and a picture: dropped on it, pasted (Ctrl+V) while it is
  shown, chosen, or made from its words with **Make its picture**. While the builder is open, a pasted picture is the
  builder's: it never goes to the composer's start frame behind it.
- **Where it is:** a click on a prop puts it in the scene, then **In the scene** says where: about the place, or in
  a character's hand: **in hand**, **right hand**, **left hand** or **both hands**. Image models often swap left and
  right, so in hand is the one to use when the side doesn't matter. A hand holds one thing, and a prop is in one
  place at a time.
- **In the prompt:** what a character holds is in their part, what is about the place is in the place's part. A video
  that starts from an image shows them already, so they aren't said then, nor in the later prompts of a sequence.
- **The usual ones come first:** a tab for each character whose preset has usual props, named after them
  (**Mira's**), then one for the place's, named after it (**Classroom**: chalk, notebooks, pencils…). The step opens
  on the first character's, and a prop picked from a character's tab goes in their hand. A preset's usual props are
  set on its card in the Character step (**Usual props**: **+ Add a usual prop…**, and × on one to take it off), or
  with **usually Mira's** on a prop in the Props step.

The built-in props and the words they are said in are `comfyui-hive/props.json`; a place's usual props are with the
place, in `environments.json`.

## Characters

**Character**, the card over the prompt, opens the prompt builder at its second step. The three steps after Environment are
about who is in the picture: up to three characters, chosen by the chips beside the steps (**+ Character** adds one,
**Remove** takes the one shown out). A character nothing was set of says nothing. Every setting starts at saying
nothing, as the places' do, and a character's part of the prompt comes before the place, which is then said as their
setting.

- **Character** is who they are, under Basics, Body, Face, Hair and Details at the left:
  - **Basics:** gender, age (an adult's: twenties to elderly), ethnicity, the kind of being for another world's story
    (an elf, an orc, an android), the skin's tone and whether it is freckled or lined.
  - **Body:** height, with the upper body's and the legs' length apart from it; body fat for the whole body, and
    muscle; then what can be set apart from the body fat: shoulders, breast size (a woman's), waist, belly, hip
    width, ass size and thighs.
  - **Face:** its shape; the eyes' size, shape and colour; the eyebrows' thickness and colour; the nose's size and
    shape; the lips' thickness and colour; cheeks and jaw; facial hair (a man's).
  - **Hair:** length (bald to waist-length), type, colour, style and fringe.
  - **Details:** makeup, nails, tattoos, piercings and scars.

  A colour is one of the named ones or any other from the picker, which the prompt names. What is only a woman's or
  a man's is offered to them, and to a character whose gender isn't said. The prompt joins what belongs together:
  size, shape and colour are one thing said of the eyes ("large almond-shaped green eyes").
- **Presets:** the first thing the Character step shows is what to start from: a new character, one of your
  presets, or one of your LoRAs that is marked as a character. A preset or LoRA can be marked **realistic** or
  **stylized** on its card, and the list has Realistic and Stylized chips that start at the style the model picked
  does best (Pony stylized, Z-Image realistic, both when it does them alike). At the right are the character's name (which tells
  two characters apart in the prompt), its LoRA, and **Save as a preset**, which keeps the character under that
  name for any chat: all of them but where they are in a place (who they are, their LoRA and sliders, what they
  wear, their pose and expression, and their words).
- **A chat follows the preset:** a chat's character of a preset has all of it as the preset has it now, so a change
  to the preset shows in every chat that has them. What a chat changes is that chat's own: the row is marked with a
  bar at its left, and the link icon beside it puts it back to the preset's. The card says how many things are the
  chat's own, with **Back to the preset** for all of them and **Save to the preset**, which makes them the preset's.
  **Save as another** makes a second preset of what is set now.
- **Warnings:** a LoRA trigger prompt that says what the builder sets (a framing like "cowboy shot", a pose, a gaze,
  an expression or a facing) fights what is set: the card and the Pose and place step warn of each such word.
- **A preset's picture:** it is one of your own,
  given as anywhere on the page: dropped on it, pasted (Ctrl+V) while the Character step is shown, or **Choose a
  picture**; or **Make its picture** makes a portrait of the preset from its own prompt, with the model picked in the
  chat when that one makes images. The presets are each account's own, kept by the rig or hub whose page it is.
- **A LoRA as a character:** under Manage LoRAs, **Character preset** on a LoRA marks it as somebody's, and the
  Character step then offers it among the presets, with its picture. A preset made here can name any of your LoRAs
  as well. Either way the LoRA's trigger prompt starts that character's part of the prompt, what is set here adds
  to it (other hair, a build), and the LoRA is added to the request's LoRA
  rows if it isn't there: the page says so, or says why not (the model takes none, or the LoRA has no files for
  it).
- **Outfit** is what they wear, by part of the body at the left: head (hats, glasses, earrings), neck (chokers and
  necklaces, scarves and ties), upper body (shirts and tops, jackets and coats, bras and bikini tops), whole body
  (dresses, suits, one-pieces), hands (gloves, rings, wrists), lower body (trousers, shorts and skirts, underwear
  and swimwear, belts), legs (socks and stockings), feet (shoes) and bags: 135 things as tiles with a picture each.
  One of a kind at a time: a click puts it on, another takes it off. What can't be worn together gives way: a dress
  takes the place of the shirt and the trousers, and **Topless**, **Bottomless** and **Barefoot** are among the
  tops, the bottoms and the shoes, each taking off what would cover the same. What is picked is listed at the
  right, each with its colour (**None** beside it takes it off again), pattern and material. With nothing picked the prompt says
  nothing of their clothes, and the model dresses them.
- **Pose and place** is how they are in this scene: a **pose** (standing, sitting, lying, moving, or doing
  something: 36, with a picture each), **where** in the place picked in the first step (a living room offers on the
  sofa, in the armchair, by the window; every place has its own), or just where in the picture, and under
  **Expression and view** their expression, where they look, from where they are seen, and how much of them the
  picture shows, and **Size in the frame**: how much of the frame's height they take (fills it, most of it, about
  half, or small and far off). Both are the whole picture's, said first. For a video, a pose that goes on (walking, dancing) is also
  said at the end as what keeps happening. A spot of one place isn't said in another: change the place and it
  waits until a place has it again.

What a character can be set to, the garments, the poses and every word each adds are in
`comfyui-hive/characters.json`, which says how it is laid out; the spots of each place are with the place, in
`environments.json`.

## Scene library

**Scene library**, in the menu (☰), is a page of its own for the builder's characters, props and places, so that a
chat isn't the only way to look after them. Its tabs are **Characters** (your presets, and the LoRAs marked as
character presets, each with the props it usually has), **Props** (yours, then the built-in ones) and **Places**,
with a search over the tab.

A tile opens the prompt builder at that step, with every step and section a chat has, on a scene of the
page's own. A character there is the preset itself: every change to it is the preset's, kept as you make it, without a
Save, and shows in every chat that has them but where a chat changed it for itself. A new character (**+ New
character**) is kept once it is saved as a preset. A prop of yours is changed, given a picture or deleted there
likewise (**+ New prop** starts one), and **+ New place** makes a place of your own (a name, indoors or outdoors, the words the prompt says of it, a LoRA if
you like and a picture), which a built-in one can start. The pictures of the builder's things are each a model's: a tile
shows the one made with the model picked, else the one it had before; **Pictures** opens a dialog that switches that
model and makes the pictures of the kinds ticked, with **Stop**. A character preset can have **variants** (**Save as a
variant** on its card): a variant is its base but for what it overrides, always with the base's LoRA; a base with
variants is one tile with a badge that opens to them. **Make character**, under an image of the chat, makes a character
preset of it, asking its name and LoRA.
The scene itself isn't kept anywhere, and no chat's composer or settings change. For an admin, the **Places** and **Props** tabs each have a bar that makes that tab's missing
built-in pictures in one go.

## Lip-sync

**Lip-sync** under a video moves the mouth in it to a speech, with LatentSync 1.6: pick one of the video's sounds, or
a sound file of yours with the words (WAV, MP3, FLAC, M4A, OGG). What comes of it is a request of its own at the end
of the chat with its own video; the one it was made from stays as it is.

- **What it does:** only the face is made anew, at 512 pixels, and put back into the picture, so the rest stays. It is
  for a real face seen from the front, not a drawn one. The video comes out at 25 pictures a second and as long as the
  speech (a shorter video is played on, forwards and back).
- **How it runs:** not in ComfyUI but as LatentSync's own program, in a Python environment of its own on the rig, so
  what it needs (an older PyTorch) never meets what ComfyUI needs. The first request on a rig installs it (a few GB)
  and fetches its helpers by itself; its two model files (5.1 GB) are downloaded under Models like any other. While
  it runs ComfyUI gives the GPU's memory back. It needs about 18 GB.
- **On an RTX 50 card** it is installed with a newer PyTorch than it was made for, which those cards need: not tried.
- **Not tried on a real rig yet:** the page, the hub and the rig's side were tested with a stand-in for LatentSync
  (`tools/fake_trainer.py`); its install and a real lip-sync have not run.
- **The speech from words:** **Add sound** with **Chatterbox** speaks the words you write (English), as one of the
  video's sounds: kept, picked and merged like the others, and offered by Lip-sync as the speech. With **A voice to
  copy**, a recording of about 10 seconds, it speaks in that voice; without one it has its own. It runs like
  LatentSync, as its own program in its own environment: the first request installs it and fetches its voice model
  (about 4 GB) by itself. **Chatterbox Turbo** is a model of its own that also makes sounds written in brackets
  (`[laugh]`, `[gasp]`); the **(i)** beside a model picker shows its tips. On the timeline a sound to speak has a **Voice**
  in its box: its own, a sound from Media, or a recording of yours. Not tried on a real rig yet either.

## Sound for a video

**Add sound** under a video makes a sound for it with a model that follows what moves in the picture: MMAudio (the
one picked first: small and quick) or HunyuanVideo-Foley (cleaner, slower). Words are optional and steer it
("footsteps on gravel", "rain"). They make effects and ambience, not speech. Both are listed under Models with the
others and are downloaded there; clicking one doesn't pick it for the composer.

- **The video stays as it is.** Each sound is a file of its own (FLAC), listed under the video as **Sound: 1 · 2 ·
  ...**. Ask as often as you like and click the one to keep: it has the tick. Clicking it again plays the video
  without sound; **×** deletes a sound (or stops one being made).
- **Playing:** opened large, the video plays with the picked sound, started, paused and moved with it. The list beside
  Download there switches between the sounds while you watch.
- **Download** gives one MP4 with the picked sound in it (the picture as it is, the sound as AAC, cut to the
  picture's length); without a picked sound, the video as it is. Deleting a video deletes its sounds.
- **Length:** a video of 1 to 60 seconds; the models are made for about 8 to 10. Through a hub the video is sent to
  the worker, so there it can be 40 MB at most.
- **The node packs:** these two models use nodes ComfyUI doesn't have by itself. The miner (v1.3 or later) installs
  them when ComfyUI starts, each at the commit `catalog.json` names under `packs`, with its Python packages; PyTorch
  and numpy stay as ComfyUI has them. A pack that can't be installed is left out and said in the miner's log, ComfyUI
  starts without it, and the model's card says it can't be used. MMAudio's pack is taken at the commit of its pull
  request 70, with which the video's frame rate is given to it: without that its sound covers only part of a 16 fps
  clip.
- **Not included: ThinkSound.** Its only ComfyUI nodes have been left unmaintained since July 2025, fail with current
  `transformers`, and pin old versions of packages ComfyUI shares.

## Timeline

A page beside the chats (**Timeline** in the menu (☰), **+ Project** over the chats) where clips from the outputs are
arranged on a timeline and exported as one video. On a rig by itself and on a hub alike.

- **A project** is a saved list of clips with their trims and positions, of one size and frame rate. Nothing changes
  an output: the export is a new one, in the project's own chat, that can be played, continued and given sound like any
  other. A project's chat is listed under **Timelines**, below the chats, and opens its timeline.
- **Edit in timeline**, under every video of the chat and of Outputs, opens that video's own project (made the first
  time). A stitched video comes as the videos it was made of, each a clip placed as it is in the stitched one: to
  trim them, fade them into each other or put others between, and export the row again. The stitched video stays.
  **Edit in timeline** under an image opens a project of its own with the image as its first clip, a still to start a video from.
  The form for a new project can also start from a picture or a video, a file of yours (chosen, dropped or pasted on the projects'
  screen) or an output; videos of yours can be added to a project like its sounds and images, and pasted onto the timeline.
- **Tracks:** one video track, and sound tracks laid over each other. A video with sound takes the video track and a
  sound track; a sound that belongs to a clip moves with it. Each sound has its volume, fade in and fade out. Sound
  files of your own (WAV, MP3, FLAC, M4A, OGG) are dropped on the timeline or on Media, and are kept with the project.
- **Stills:** an image from Media's **Images** tab (the outputs' pictures, or PNG, JPEG and WebP files of your own dropped
  on the timeline or on Media, kept with the project) goes on the video track as a clip of one frame. Its ends drag out
  to hold it for any length; it has no speed or sound, and is drawn, previewed and exported fitted like a video's frame.
  A gap right before or after it starts or ends on it as on any clip.
- **Several clips:** Ctrl-click adds a clip to those picked or takes it out, Shift-click picks a span of the video
  track. **Remove** takes them out as one Undo step and a drag moves them together.
- **On the timeline:** drag a clip to move it and its ends to trim it, drag the ruler to scrub, Ctrl and the wheel (or
  the slider) to zoom. A clip shows its first and last frame, and frames between where there is room. A track's lower
  edge is dragged to make it higher (the bar's **Height** sets the video track's, whose pictures grow with it).
  **Snap to start** moves the picked clip back to where the one before it ends, or with none picked, everything back
  until the first clip starts at the start. Two clips that
  meet can be faded into each other (Crossfade into next): they lie over each other for that long.
- **Speed and pitch:** the Inspector gives every clip a **Speed**, from 0.25 to 4 times: it shows the same part of its
  file in less or more time, so it gets shorter or longer on the timeline. On the video track the clips after it move
  by the difference, and a clip's own sound keeps its speed; a sound by itself takes no more room than there is before
  the next one on its track. A sound keeps its pitch at any speed, and has a **Pitch** of its own, up to an octave
  (12 semitones) up or down, that leaves its length alone, beside its **Volume** and fades. Both are made on the rig
  (FFmpeg's `atempo`, and for the pitch the samples played at another rate first), the same for the preview as for
  the export, so the two sound alike; a sound at a new speed or pitch is heard a moment after it is set.
- **Filling a gap:** dragging across an empty stretch of the video track makes a gap, and the Composer panel (the
  chat's own composer, moved in) makes a video for it: from the last frame of the clip before, and, with a model that
  takes an end frame (Wan 2.2 14B, LTX-2.5 and MiniMax H3, *First and last frame*), to the first frame of the clip after. Only the models that
  can do what the gap needs, at the project's size, are offered; the others say why not. The gap shows the request's
  progress and becomes the clip; Another attempt makes one more to switch between. A fill without an end frame is
  made a little longer and the rest stays past the clip's end, to be dragged out; one with an end frame is kept whole
  and the clips after it move to fit, since it meets them only on its last frame.
- **Gap drafts:** each gap keeps its own setup of the composer (model, prompt, scene, LoRAs, numbers, Repeat, frames
  ticked) as its draft, which the composer shows while the gap is picked; it is kept with the project, without an Undo
  step. A gap's prompt can have words **Before** and **After** it for what many clips share. **Fill between** in the
  bar puts a gap with both ends ticked in every empty stretch between two clips (within those picked, if several are),
  and a gap nothing was asked for yet reads *Unfinished*. With several gaps picked the composer edits all their drafts
  at once: a field that differs reads mixed and a change sets that field alone on each, the prompt is read-only until
  **Replace on all…**, and **Make identical** copies the shown draft to the others. **Generate** sends each its own
  request and says which weren't sent and why; **Generate unfinished** sends every gap nothing is being made for (asking
  first over 8), one at a time, and a gap that starts or ends on a gap still to be made waits for it.
- **Sound after a fill:** a fill made to end on the clip after moves every sound that starts where its gap ended or later
  by the same amount as the video clips after it, so all of it still lines up; a sound running across the gap stays.
- **Reverse:** **Reverse** (the timeline's bar, a clip's menu, the More menu on a phone, or a tick in the Inspector) plays the
  picked videos and sounds from the last frame of what they show to the first, where they are and as long, with a video's
  sound reversed with it; such a clip has a rewind badge. Split, trim, gap ends and volume curves follow its direction.
- **Lips and sound tracks:** a **Lips** track sits above the video track, and sound tracks can be added (+ under the last) and
  deleted (the trash beside a name, once confirmed; Undo brings it back). Alt and dragging across an empty stretch of a sound
  track or the Lips track (or **Make a sound here**, **Make a lip-sync here** in the menu) makes an unfinished clip, set up in a
  box on the clip: a sound is made by a sound model for the picture over its time, a lip-sync by a lip-sync model from the
  picture there and the sound tracks mixed, and a lip-sync shows instead of the video under it in the viewer and the export.
- **Media and Selected:** Media has the chat's mark chips, a green dot on new files, ratings on its tiles, tiles in the shape of
  their pictures, a **+** in each tab (New video, New image, New sound), the requests being made, and **Find in media** in a clip's
  menu. A click on a tile shows the file in the **Selected** panel, with the swipe viewer, its links (**Put at playhead**, **Put
  at the end**) and its own keys; a video's tile plays in the Viewer. Sounds show their marks too (a star or thumb on the tile, the chips
  **Liked or better** and **Favorites**), and a sound's tile menu marks it, as a phone needs. An image of yours has the links of an
  output's image (**Download**, **Change…**, **Use as start frame**, **Use as end frame**). A file dropped on the timeline goes in at the playhead.
  **Delete** (its tile, its menu, Selected, the viewer) deletes a sound or image file of yours after asking, for good; not one a clip uses.
  An image of Media goes into the composer's Start or End frame: dropped on it, copied and pasted into it, or **Use as start frame** /
  **Use as end frame** in its tile's menu.
- **Repeat in a gap:** a gap sent with Repeat over 1 has its videos picked from: **Pick one…** rates them in the swipe viewer and
  the one liked goes in. A gap with attempts to pick from has a **Rate** button on its clip, which opens them in the swipe viewer (attempts already marked are skipped). **Match colours** works on a still of the video track too.
- **Viewer:** **Loop**, and a **Quality** for how sharp the preview is (Low 640, Standard 960, High 1920 or Full), made by the
  rig the first time it is asked for; the export is not changed by it.
- **Try again, Cancel and Play the picked:** a clip made already can be made again with **Try again** (its menu, a double click,
  the Inspector): a sound or lip-sync opens its box with what it was made with and the new one takes its place once done; a
  video clip becomes a gap set up as it was made, with **Put the old clip back**. A sound or lip-sync being made says how far
  it is on the clip and has **Cancel**. The Viewer's **Play the picked**, beside Loop, plays only the picked clips' stretch.
- **Stitch and Unstitch:** **Stitch** makes the picked clips of the video track one clip, a video of them as they are there
  with their sounds, made in the project's chat as an export is and put in their place once made (one Undo step).
  **Unstitch** takes a stitched video apart again, into the clips and sounds stitched here as they were, or into the videos
  of a row Continue stitched in the chat.
- **On a phone:** the timeline editor has a layout of its own: the picture over the timeline, whose playhead stays in the
  middle while a finger drags the clips under it, a bar under them of what can be done with what is picked, and the other
  panels as sheets that come up over part of the screen. A tap picks a clip, which then has handles to trim it; holding
  a clip picks it up to move it, and holding and letting go calls up a menu of what Ctrl, Shift, Alt or a double click do.
  Where a picture goes into a box (the start and end frames, a LoRA's picture), a finger held there brings up the phone's own Paste.
- **Sizes and frame rates:** a project's size and frames a second are set when it is made (the chat's sizes, or
  matched to a picture or video), with the models that can't make that size named, and the nearest size the ticked
  models all make offered. A clip of another shape is shown whole with bars, or cropped. A clip of another frame rate
  keeps its speed: each frame of the export shows the frame of the clip that is on screen then.
- **Panels:** Media, Viewer, Inspector, Composer, Chat, Chats, Models and Timeline are arranged by dragging: a tab onto
  another panel puts the two together as tabs or, at an edge, side by side; the lines between panels resize them. A and
  B are given layouts; your own are saved by name on the rig or hub.
- **The preview is approximate.** The viewer plays a small copy of each clip (made once and kept a week under
  `<data>/timeline/cache`), fetched whole so playing doesn't wait for the rig, and mixes the sound in the browser.
- **The export** is made by the program itself (PyAV), not by ComfyUI, so it waits for no GPU. It is written with the
  graphics card's H.264 encoder where PyAV has one that works, else with x264. Continue's Stitch uses the same code.

*First and last frame* is the image-to-video workflow with the end image added (`tools/build.py`, "derive"): for
Wan 2.2 14B with `WanFirstLastFrameToVideo` in place of `WanImageToVideo`, for MiniMax H3 as its node's `last_frame`.
For LTX-2.5 the end image is an `LTXVAddGuide` at the last frame (`frame_idx` -1) in each of its two passes, the half
size one and the upscaled one, with `LTXVCropGuides` taking the guide back out of the latent after each sampling.
Those nodes can't do without their image, so its `end_image` input names them under `without`, each with what takes
the place of its outputs: with no end image `page.py` takes them out and the workflow is LTX's image to video exactly.
Wan's was made for real on a rig (RTX 4090, ComfyUI v0.45.0): 2 seconds at 640 x 368 in 63 s, starting on the start
image and ending on the end image. MiniMax H3's and LTX-2.5's were only checked against that ComfyUI's node
definitions, not run.
Not tried yet: the graphics card's encoder, which the PyAV this was written with doesn't have.

## What happens on a switch

**Switching to this flight sheet:** it waits while any GPU process or Docker container is running, so it can't take a
GPU from a rental (a backstop only: take the node off the market first), and while no DOCKER drive is mounted. Then it
sets the firewall rules for both ports, stops and disables `hive-watchdog`, installs Python and starts the page, installs ComfyUI and
PyTorch the first time (or after a version change), and starts ComfyUI on the private LAN address.

**Switching away (or a stop or reboot):** ComfyUI and the page end, a download in progress stops (it continues next
time), and the firewall rules go. `h-guard.sh` does the same if `h-run.sh` is killed outright. A request that was
running is marked failed. The watchdog stays stopped and disabled, on any flight sheet, until you turn it back on
yourself (`sudo systemctl enable --now hive-watchdog`).

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
   (the negative prompt, the sampler) and `clip_skip` skips the text encoder's last layers. An input of kind `bool` is a switch of the template, shown as on or off with its
   `title` as the hint (the task's `set` gives what it is when a request doesn't say). A model trained on tags
   rather than descriptions says `"prompt_style": "tags"`, which the Environment picker writes its prompt by.
   Models sharing a task
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
- `page.py`, `page.html`, `timeline*`, `dock.*`, `catalog.json`, `workflows/`: the page program (with its timeline
  editor, in files of its own), its models and their workflows. They are
  not kept in this repository: `release.sh` puts them into the package from `xefier-comfyui`, where they are made
  (and where `tools/` is)
- `h-stop.sh`: puts the rig back; safe to run repeatedly
- `h-update.sh`: the miner updating itself to the newest release
- `h-guard.sh`: runs `h-stop.sh` if `h-run.sh` is killed, and keeps the watchdog stopped and disabled
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

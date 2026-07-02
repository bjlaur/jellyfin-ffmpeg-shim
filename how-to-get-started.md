## How to get started with a new hardware backend

You don't need to know FFmpeg inside and out to work on this. If you're
generally comfortable developing software, have some useful test media, and
check what your tools and AI assistant are actually doing, you can get started.

### Find a good HDR sample

Start with a short, visually demanding HDR clip. In my case, I used
`matrix-dv-sample-0253-0444.mkv`, a cut of *The Matrix* spanning 2:53 to 4:44
from a remux. It contains Dolby Vision with an HDR10 fallback and also requires
subtitle burn-in, at least on Jellyfin Web. An AI assistant can help construct
the FFmpeg command that extracts a short sample from media you are authorized
to use.

A short clip makes repeated tests fast while preserving the streams, metadata,
and difficult scenes that matter. Record its origin and inspect it with
`ffprobe` or MediaInfo instead of trusting its filename.

### Prove the idea with FFmpeg first

Before getting into the shim, see if the idea works with `jellyfin-ffmpeg` at
all. My first step was to have AI create these two files:

- `matrix-dv-sample-0253-0444-hdr-to-hdr.mkv` — the new method
- `matrix-dv-sample-0253-0444-hdr-to-sdr.mkv` — the control

I gave it the raw `jellyfin-ffmpeg` commands from Jellyfin's FFmpeg log and had
it model the new command after those. This gives you a simple proof of concept
before you start changing code.

### Build out the test set

Once the proof of concept works, find files that cover these cases:

1. Dolby Vision with HDR fallback.
2. Dolby Vision without HDR fallback.
3. Subtitles that need to be burned in.
4. Any other cases you want covered.

### Make sure the GPU is doing the work

Use `btop` while you are testing and make sure GPU usage is at or near
100%. Tools such as `intel_gpu_top`, `nvtop`, or `radeontop` can give you a more
detailed view if you need it.

This matters because AI may get the command working by quietly moving some of
the work to software. That was not good enough on my iGPU. Moving frames
between the GPU and system memory used too much of the available bandwidth, so
the pipeline could not keep up. A discrete graphics card has significantly more
bandwidth and might cope with that better, but it is still not ideal to have
much software processing in the pipeline.

### Leave a detailed handoff

Make a new handoff file for your AI, such as `handoff-amd.md` or
`handoff-yourname.md`. Tell it to write a VERY detailed account of what is
going on so future agents can pick up the work without having to rediscover
everything. It should include:

- The goal, current status, and hardware/software environment.
- Details about each test file and what path it is meant to exercise.
- The original Jellyfin commands and the experimental commands that were tried.
- What worked, what failed, and how you know.
- Performance results and any places where work fell back to software.
- The files changed, tests added, open questions, and next things to try.

### Keep an eye on the AI

AI will make bad decisions, so keep a watchful eye on what it is doing and be
ready to push back when it misses the mark.

I recommend Codex because it seemed to really understand this stuff. It was
even able to make an FFmpeg patch, which is frankly black magic to me.

Other than that, try not to make a mess of things. :P

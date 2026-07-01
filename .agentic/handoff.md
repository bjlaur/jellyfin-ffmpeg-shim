# Jellyfin FFmpeg HDR Shim: Engineering Handoff

## Status at handoff

This repository contains a working Jellyfin FFmpeg wrapper that selectively changes Jellyfin-generated HDR-to-SDR transcodes into HDR-preserving transcodes. It supports:

- Software HEVC encoding through `libx265`.
- Intel VAAPI decode/filter surfaces mapped into `hevc_qsv` encoding.
- A blocking Jellyfin `/Sessions` lookup used to decide whether a client is allowed to receive HDR.
- Case-insensitive user/device allow and deny rules.
- An independent `-minrate` rewrite based on Jellyfin's `-maxrate`.
- JSON configuration.
- Arch Linux packaging.

The initial working baseline is committed as:

```text
291ef6349f2a06d3c0f9097fa55061280dfc2e6a
291ef63 Initial Jellyfin HDR FFmpeg shim
```

At the time this document was written:

- Git branch: `master`
- Repository package version: `0.1.0-10`
- Installed package: `jellyfin-ffmpeg-shim 0.1.0-5`
- The installed package version changes during active testing; verify it with `pacman -Q jellyfin-ffmpeg-shim` rather than relying on this snapshot.
- Jellyfin FFmpeg package: `jellyfin-ffmpeg 1:7.1.4p1-1`
- Python package: `python 3.14.5-1`
- The latest observed software and VAAPI/QSV rewrites both completed successfully.

The shim now performs a bounded synchronous ffprobe safety check. Profile 5 and sources without a verified HDR10-compatible base are denied before rewrite.

## Project goal

Jellyfin normally generates FFmpeg commands that tone-map HDR sources to SDR for clients that request transcoding. This shim intercepts those commands and, only for explicitly allowed clients, rewrites supported commands so the video remains HDR while it is resized/re-encoded.

The intended behavior is:

```text
Jellyfin starts shim with FFmpeg argv
  -> shim loads JSON config
  -> optional minrate rewrite
  -> recognize supported Jellyfin HDR-to-SDR command
  -> synchronously inspect Jellyfin sessions
  -> apply deny/allow rules
  -> rewrite supported pipeline to preserve HDR
  -> execv() the real Jellyfin FFmpeg
```

The shim does not remain resident. It replaces itself with FFmpeg using `os.execv()`.

## Repository files

### `jellyfin-ffmpeg-shim`

The complete runtime shim. It is intentionally a single executable Python file and currently uses only the Python standard library.

### `shim.json.example`

Complete example configuration. The package installs it as `/etc/jellyfin/shim.json`.

The real config contains a Jellyfin API key and must not be committed. `.gitignore` excludes a repository-local `shim.json`.

### `PKGBUILD`

Arch Linux package definition.

- Package: `jellyfin-ffmpeg-shim`
- Version: `0.1.0`
- Release: `5`
- Architecture: `any`
- Dependencies: `python`, `jellyfin-ffmpeg`
- Installs the executable to `/usr/bin/jellyfin-ffmpeg-shim`
- Installs config to `/etc/jellyfin/shim.json`
- Declares the config as a pacman backup file
- Uses `SKIP` checksums during active development
- License is currently declared `custom:unlicensed`; the project needs a real license decision

### `jellyfin-ffmpeg-shim.install`

Pacman install/upgrade hook.

- Attempts to set `/etc/jellyfin/shim.json` to `root:jellyfin`, mode `0640`.
- Prints a prominent post-install activation checklist.
- Reminds the administrator to edit the API key/rules and update `/etc/jellyfin/jellyfin.env`.

### `.gitignore`

Excludes Python caches, virtual environments, real config, logs, makepkg output, package archives, and common editor files.

### Removed file

An asynchronous helper named `jellyfin-ffmpeg-shim-hdr-client-detect.py` existed during discovery. It polled for 20 seconds and wrote large JSON dumps. It was deliberately removed. Do not restore subprocess-based asynchronous decision making: the rewrite decision must be complete before FFmpeg starts.

## Installed paths and server integration

Expected installed paths:

```text
Shim:          /usr/bin/jellyfin-ffmpeg-shim
Real FFmpeg:   /usr/lib/jellyfin-ffmpeg/ffmpeg
Config:        /etc/jellyfin/shim.json
Main log:      /var/log/jellyfin/jellyfin-ffmpeg-shim.log
Jellyfin env:  /etc/jellyfin/jellyfin.env
```

The config path can be overridden for testing or alternate installations:

```bash
JELLYFIN_SHIM_CONFIG=/path/to/shim.json /usr/bin/jellyfin-ffmpeg-shim ...
```

Jellyfin must be launched with the shim as its FFmpeg binary. On this server that is controlled by `/etc/jellyfin/jellyfin.env`, ultimately producing:

```text
--ffmpeg=/usr/bin/jellyfin-ffmpeg-shim
```

After changing `jellyfin.env`, restart Jellyfin:

```bash
sudo systemctl restart jellyfin
```

An earlier installation used `/usr/local/bin/jellyfin-ffmpeg-shim`. That path is obsolete. No repository references to `/usr/local/bin` should remain.

## Configuration schema

The full current example is:

```json
{
  "shim": {
    "kill_switch": false,
    "enable_hdr_to_hdr": true,
    "enable_bitrate_min": true,
    "enable_blocking_client_decision": true,
    "enable_filter_complex_hdr_to_hdr": false,
    "log_full_argv": true
  },
  "jellyfin": {
    "url": "http://127.0.0.1:8096",
    "api_key": "PASTE_YOUR_API_KEY_HERE"
  },
  "paths": {
    "ffmpeg_binary": "/usr/lib/jellyfin-ffmpeg/ffmpeg",
    "log_file": "/var/log/jellyfin/jellyfin-ffmpeg-shim.log"
  },
  "tuning": {
    "minrate_ratio": 0.70,
    "blocking_decision_poll_delays_seconds": [0.0, 0.25, 0.75, 1.5, 2.5],
    "blocking_decision_api_timeout_seconds": 1.0
  },
  "hdr_access": {
    "allow_list": [
      {
        "username": "nullstring",
        "devices": ["chrome", "midoriko"]
      }
    ],
    "deny_list": [
      {
        "username": "nullstring",
        "devices": ["firefox"]
      },
      {
        "username": "jena"
      }
    ]
  }
}
```

All listed fields are required. The Python source intentionally does not duplicate operational defaults.

The only hardcoded deployment fallback is:

```text
/usr/lib/jellyfin-ffmpeg/ffmpeg
```

That emergency path exists so invalid/missing configuration can still execute the real FFmpeg unchanged.

### Kill-switch behavior

`kill_switch: true` means total passthrough:

- No Jellyfin API call.
- No minrate rewrite.
- No HDR rewrite.
- Execute real FFmpeg with the original arguments.

The shim also forces the kill switch when:

- The config file is missing.
- JSON is invalid.
- A required field is absent or has the wrong type.
- The API key is blank.
- The API key is still `PASTE_YOUR_API_KEY_HERE`.

On a malformed config the real FFmpeg path resets to the emergency hardcoded path.

### Access rules

Rule matching uses Unicode-aware `casefold()` for both usernames and device names.

Rules look like:

```json
{
  "username": "nullstring",
  "devices": ["chrome", "midoriko"]
}
```

Semantics:

- A username and one listed device must both match.
- Matching is case-insensitive.
- Omitting `devices` matches every device for that user.
- Deny rules are evaluated before allow rules.
- Any matching deny rule rejects HDR.
- With no matching allow rule, HDR is rejected.
- Rejection means Jellyfin's original SDR behavior passes through; minrate may still be applied.

Current intended policy:

```text
nullstring + Chrome   -> allow HDR
nullstring + midoriko -> allow HDR
nullstring + Firefox  -> deny HDR
jena + any device     -> deny HDR
everything else       -> deny HDR
```

## Startup/configuration safety

The module begins in a fail-safe state:

- Kill switch enabled.
- Every optional feature disabled.
- Empty API credentials and rule lists.
- Emergency real FFmpeg path available.

`load_config()` validates JSON types and required keys. Feature flags must be JSON booleans, not `0`/`1` or strings. Numeric lists must be non-empty, ascending, and non-negative.

Logging failures are swallowed because logging must never stop playback.

## Main execution flow

`main()` performs these operations:

1. Capture `sys.argv[1:]` as the original FFmpeg argv.
2. If kill switch is active, log when possible and `execv()` real FFmpeg unchanged.
3. Classify the command.
4. Run the blocking client decision only for recognized rewrite candidates.
5. Apply minrate rewrite independently.
6. Apply HDR rewrite only when classification and client decision permit it.
7. Log configuration, decisions, original argv, rewritten argv, and final status.
8. Replace the shim process with the real FFmpeg process:

```python
os.execv(REAL_FFMPEG, [REAL_FFMPEG] + rewritten)
```

Do not change this to a long-lived subprocess without a specific reason. `execv()` preserves Jellyfin's process management expectations.

## Bitrate/minrate rewrite

When enabled, every parseable `-maxrate` or `-maxrate:*` receives a matching `-minrate` at the configured ratio.

With `minrate_ratio: 0.70`:

```text
-maxrate 19616000 -> -minrate 13731200 -maxrate 19616000
-maxrate 19616001 -> -minrate 13731200 -maxrate 19616001
```

Suffixes are preserved:

```text
-maxrate:v:0 X -> -minrate:v:0 Y
```

Existing minrate options are updated rather than duplicated. Values accept plain numbers and `k`, `m`, or `g` suffixes.

Minrate is intentionally independent from the HDR decision. A denied or unsupported HDR rewrite can still receive minrate unless the global kill switch is active.

## Blocking Jellyfin client decision

### API

The shim synchronously calls:

```text
GET http://127.0.0.1:8096/Sessions
X-Emby-Token: <API key>
Accept: application/json
```

Jellyfin's `/Sessions` endpoint does not offer response field projection. The complete response is downloaded and parsed in memory, but only compact summaries are retained/logged. The API key is never logged.

Do not add `ActiveWithinSeconds` back without strong evidence. It was tested with `30` seconds and returned zero sessions during FFmpeg startup, hiding the initiating session. Unfiltered `/Sessions` returned the useful session data.

The configured poll schedule is interpreted as absolute elapsed offsets. Default:

```text
0.0, 0.25, 0.75, 1.5, 2.5 seconds
```

The shim sleeps only the difference between successive offsets.

### Parsed command match inputs

The command parser extracts:

- Input paths from `-i`.
- Input basenames.
- Final output path/basename.
- HLS segment filename stem.

`file:` is removed from local input paths.

### Session scoring

Current score contributions:

```text
+20  session has TranscodingInfo
+10  session has NowPlayingItem
+100 full input path occurs in session JSON
+50  input basename occurs in session JSON
+25  output basename occurs in session JSON
+25  HLS segment/output stem occurs in session JSON
```

The observed exact match score was `180`:

```text
20 TranscodingInfo + 10 NowPlayingItem + 100 full path + 50 basename
```

### Confidence selection

High confidence:

- Best score is at least `100`.
- Exactly one session has that best score.

Medium confidence:

- Exactly one session has `TranscodingInfo`.

Low confidence/fail closed:

- No sessions.
- No transcoding session.
- Multiple ambiguous transcoding sessions.
- API failure.

Important behavior: the shim returns immediately on a medium-confidence candidate. It does not continue polling in hopes of obtaining a later exact path match.

### Known stale-session concern

One successful run selected immediately with:

```text
score=20
confidence=medium
reason=exactly one active transcoding session
```

That does not prove `TranscodingInfo` belonged to the current FFmpeg request. It could theoretically have been stale from a previous playback. Later runs obtained high-confidence score `180`, but one VAAPI/QSV run again used medium confidence `20`.

This is an acknowledged race. Possible future improvements:

- Continue polling briefly after a medium candidate to seek an exact path match, while retaining medium as a fallback.
- Compare session/transcode output paths or HLS hash more aggressively.
- Inspect timestamps if Jellyfin exposes reliable activity/transcode start timestamps.
- Fail closed on medium confidence via a configurable policy.
- Never blindly assume the sole stale transcode is current.

## Command classification

The classifier distinguishes:

- Software `libx265` pipeline with a simple `-vf`/`-filter:v` Jellyfin `tonemapx` graph.
- Supported Intel VAAPI-to-QSV pipeline with `hevc_qsv`, `tonemap_vaapi`, `hwmap=derive_device=qsv`, `format=qsv`, and VAAPI hardware output.
- `-filter_complex` graphs.
- Other hardware pipelines.
- Commands that are not HDR-to-SDR candidates.

Only recognized simple filter graphs are rewritten.

## Software HDR-preserving rewrite

Recognized source shape includes a simple filter containing all current markers:

```text
tonemapx=tonemap=bt2390
t=bt709
m=bt709
p=bt709
format=yuv420p
```

The SDR tonemap portion is replaced with:

```text
format=yuv420p10le
```

Example transformation:

```text
Before:
setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc,
scale=...,
tonemapx=tonemap=bt2390:desat=0:peak=100:t=bt709:m=bt709:p=bt709:format=yuv420p

After:
setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc,
scale=...,
format=yuv420p10le
```

The shim then forces:

```text
-profile:v:0 main10
-pix_fmt yuv420p10le
-color_primaries bt2020
-color_trc smpte2084
-colorspace bt2020nc
-color_range tv
```

It updates/adds these x265 parameters:

```text
repeat-headers=1
hdr10=1
colorprim=bt2020
transfer=smpte2084
colormatrix=bt2020nc
```

No luminance tonemapping is intended. The goal is transcoding/resizing while preserving the HDR10-compatible base image.

## Hardware VAAPI/QSV HDR-preserving rewrite

The supported hardware pipeline is intentionally narrow and matches Jellyfin's observed Intel command:

```text
-init_hw_device vaapi=va:,vendor_id=0x8086,driver=iHD
-init_hw_device qsv=qs@va
-filter_hw_device qs
-hwaccel vaapi
-hwaccel_output_format vaapi
-codec:v:0 hevc_qsv
-vf setparams=...,
    procamp_vaapi=b=16,
    tonemap_vaapi=format=nv12:p=bt709:t=bt709:m=bt709:extra_hw_frames=32,
    hwmap=derive_device=qsv,
    format=qsv
```

The shim removes both SDR-specific filters:

- `procamp_vaapi`
- SDR `tonemap_vaapi`

It inserts:

```text
scale_vaapi=format=p010:
  out_color_matrix=bt2020nc:
  out_color_primaries=bt2020:
  out_color_transfer=smpte2084:
  out_range=limited
```

The resulting graph is effectively:

```text
setparams BT.2020/PQ
  -> scale_vaapi P010 BT.2020/PQ limited
  -> hwmap derive_device=qsv
  -> format=qsv
  -> hevc_qsv Main10
```

It forces:

```text
-profile:v:0 main10
-color_primaries bt2020
-color_trc smpte2084
-colorspace bt2020nc
-color_range tv
```

It intentionally does not add software `-pix_fmt yuv420p10le`; QSV hardware surfaces remain `qsv`, while `scale_vaapi` provides P010 surfaces.

The installed Jellyfin FFmpeg build was verified to expose:

- `scale_vaapi` with `format`, output matrix/primaries/transfer/range controls.
- `hevc_qsv` with `main10` profile.
- `hevc_qsv` formats including `p010le` and `qsv`.

The first real observed hardware rewrite succeeded in launching and logged:

```text
SUCCESS: HDR_TO_HDR_REWRITE_APPLIED (VAAPI/QSV)
```

Its client decision was medium confidence (`score=20`), not an exact path match.

## No tonemapping policy

The project decision is now: preserve HDR while transcoding; do not map luminance to a fixed target.

Historical note: an earlier software implementation used a Mobius tone map with a 400-nit output target. A temporary hardware implementation also targeted 400 nits using HDR-to-HDR `tonemap_vaapi`. Both were removed after clarifying the requirement.

Do not reintroduce 400-nit or 1000-nit target mapping unless the project explicitly adds display-targeted tone mapping as a separate feature.

Jellyfin's original commands target SDR:

```text
Software: peak=100 with BT.709/yuv420p
Hardware: tonemap_vaapi format=nv12, BT.709
```

Those filters must be removed/replaced for HDR preservation.

## Dolby Vision behavior and critical limitation

### What works conceptually

Dolby Vision Profile 7 and Profile 8.1 normally have an HDR10-compatible base layer. Re-encoding the decoded base layer while dropping Dolby Vision RPU/enhancement information can produce ordinary HDR10-compatible HEVC.

FFmpeg's HEVC decoder decodes only the base layer by default. A fresh HEVC encode does not automatically carry the original Dolby Vision RPU or enhancement layer.

For the current sample, Dolby Vision Profile 7.6/HDR10-compatible base, the intended output is standard HDR10-like Main10 BT.2020/PQ.

### What is denied now

Dolby Vision Profile 5 does not have an HDR10-compatible base layer. It uses Dolby Vision reshaping. Simply removing Dolby Vision metadata and labeling decoded/re-encoded output BT.2020/PQ is not a valid general Profile 5 to HDR10 conversion and can produce incorrect colors.

The current safety probe denies Profile 5 and other sources without a verified HDR10-compatible base layer. Conversion of those sources is not implemented yet.

### Relevant installed FFmpeg capability

The installed `tonemapx` filter reports:

```text
apply_dovi <boolean> Apply Dolby Vision metadata if possible (default true)
tonemap=none
output t=smpte2084, m=bt2020, p=bt2020
```

For a future software Profile 5 conversion, the likely conceptual filter is:

```text
tonemapx=tonemap=none:apply_dovi=1:
  t=smpte2084:m=bt2020:p=bt2020:r=tv:
  format=yuv420p10le
```

This is Dolby Vision reshaping without luminance tonemapping.

`tonemap_vaapi` is documented as accepting HDR10 input. Pure VAAPI is not sufficient for Profile 5 reshaping. A Profile 5 hardware path would need either:

- A hybrid pipeline: hardware decode, download frames, software `tonemapx apply_dovi`, upload, hardware encode; or
- Another GPU filter with correct Dolby Vision reshaping support; or
- Fail closed and retain Jellyfin's original behavior.

### Implemented safety gate and next conversion task

The fail-closed source probe is implemented. The next task is conversion of incompatible HDR sources while preserving source luminance intent.

Desired initial policy:

```text
Plain HDR10 / compatible HLG policy        -> allow supported HDR preservation
DV with verified HDR10-compatible fallback -> allow supported HDR preservation
DV Profile 5 / no HDR10 fallback            -> skip HDR rewrite for now
Unknown profile or probe failure             -> skip HDR rewrite
```

The FFmpeg argv does not reliably expose the DV profile. Likely approaches:

1. Synchronously run `/usr/lib/jellyfin-ffmpeg/ffprobe` on the local input path with a strict timeout and compact JSON output.
2. Read `DvProfile`, `DvBlSignalCompatibilityId`, and related video stream fields from the matched Jellyfin session, but session data can arrive too late and matching can be medium-confidence/stale.
3. Combine both: use a high-confidence Jellyfin media stream result when available, otherwise bounded `ffprobe`.

If using ffprobe:

- Add `ffprobe_binary` and timeout to `shim.json` rather than introducing new operational magic strings.
- Probe only recognized candidate commands.
- Probe only local file inputs.
- Log compact results, never the entire probe response unless explicitly debugging.
- Fail closed on timeout/error/missing fields.
- Be careful that invoking ffprobe through `subprocess.run()` is justified here; it is a bounded synchronous media probe, unlike the removed asynchronous decision helper.
- Determine policy from actual FFprobe output on representative P5, P7.6, P8.1, and HDR10 files before hardcoding profile assumptions.

## Unsupported command shapes

### `-filter_complex`

Subtitle burn-in/overlay graphs generally use `-filter_complex`. They remain unsupported.

Expected behavior:

```text
BAIL: HDR->SDR tonemap found inside -filter_complex; this is usually subtitle burn-in/overlay.
```

`enable_filter_complex_hdr_to_hdr` exists in JSON but implementation deliberately still bails even if set true. It is a future feature flag, not a completed implementation.

Do not perform regex surgery on arbitrary overlay graphs without explicit tests.

### Other hardware pipelines

Only the observed Intel VAAPI-to-QSV graph is supported. Unsupported hardware encoders/filter graphs fail closed and preserve Jellyfin behavior.

Examples requiring separate implementation/testing:

- Pure `hevc_vaapi`
- NVENC/CUDA
- AMD VAAPI variations
- VideoToolbox
- OpenCL/libplacebo graphs
- Different QSV mapping/filter arrangements

The current unsupported-hardware bail message still contains historical wording about a software-only v1 and could be improved.

## Logging

Default log:

```text
/var/log/jellyfin/jellyfin-ffmpeg-shim.log
```

Every launch logs:

- Timestamp and separator.
- Loaded config path and config error.
- Real FFmpeg and log path.
- Feature state.
- Minrate ratio.
- Access rules (never API key).
- Mode summary.
- Blocking session polls and decision.
- Bitrate changes.
- HDR classification/rewrite actions.
- Full original and rewritten argv when enabled.
- Final HDR status.

Final statuses:

```text
HDR_TO_HDR_STATUS: ENABLED_AND_APPLIED
HDR_TO_HDR_STATUS: ENABLED_BUT_NOT_APPLIED_SEE_BAIL_REASON
HDR_TO_HDR_STATUS: DISABLED
```

Useful inspection commands:

```bash
tail -n 250 /var/log/jellyfin/jellyfin-ffmpeg-shim.log

grep -nE 'BLOCKING|DECISION|MODE:|SUCCESS|BAIL|HDR_TO_HDR_STATUS' \
  /var/log/jellyfin/jellyfin-ffmpeg-shim.log
```

Logs contain full media paths and FFmpeg commands when `log_full_argv` is enabled. Treat them accordingly.

## Observed runtime history

### Filtered session failure

With `ActiveWithinSeconds=30`, every poll returned zero sessions:

```text
delay=0.0  session_count=0
delay=0.25 session_count=0
delay=0.75 session_count=0
delay=1.5  session_count=0
delay=2.5  session_count=0
DECISION: DENY reason='no active sessions'
```

The activity filter was removed.

### Unfiltered medium success

```text
POLL: delay=0.0 session_count=1 best_score=20
user='nullstring' device='Chrome' client='Jellyfin Web'
DECISION: ALLOW confidence=medium
```

### Exact high-confidence successes

Later runs showed:

```text
POLL: delay=0.0 session_count=1 best_score=180
DECISION: ALLOW confidence=high
```

### Hardware success

The observed hardware source command used:

```text
hevc_qsv
VAAPI input surfaces
procamp_vaapi
tonemap_vaapi SDR output
hwmap derive_device=qsv
format=qsv
```

The shim rewrote it to P010 HDR-preserving `scale_vaapi`, QSV Main10, and BT.2020/PQ output. FFmpeg launched successfully and the shim logged the VAAPI/QSV success marker.

The current test media path was:

```text
/mnt/bigdisk/torrents/videos/tv/matrix-dv-sample-0253-0444.mkv
```

It is a Dolby Vision Profile 7.6 / HDR10-compatible sample.

## Testing and validation

There is no committed automated test suite yet. Development used inline Python assertions against `runpy.run_path()` plus syntax/config/package checks.

Minimum static validation:

```bash
python3 -m py_compile jellyfin-ffmpeg-shim
python3 -m json.tool shim.json.example >/dev/null
bash -n PKGBUILD jellyfin-ffmpeg-shim.install
makepkg --printsrcinfo >/dev/null
git diff --check
```

Build locally:

```bash
makepkg -f
```

Install/update:

```bash
sudo pacman -U ./jellyfin-ffmpeg-shim-0.1.0-5-any.pkg.tar.zst
```

Because `/etc/jellyfin/shim.json` is a pacman backup file, package updates do not blindly replace the administrator's configured API key/rules. New schema fields may arrive in `.pacnew`; check for it:

```bash
sudo find /etc/jellyfin -maxdepth 1 -name 'shim.json.pacnew' -ls
```

After package installation:

```bash
sudoedit /etc/jellyfin/shim.json
sudo systemctl restart jellyfin
```

Confirm installed source matches repository when expected:

```bash
sha256sum ./jellyfin-ffmpeg-shim /usr/bin/jellyfin-ffmpeg-shim
pacman -Q jellyfin-ffmpeg-shim
```

### Recommended future tests

Create a real test suite before expanding rewrite shapes. At minimum cover:

- Valid/missing/invalid JSON.
- Missing/placeholder API key forces total passthrough.
- Emergency FFmpeg fallback on malformed config.
- Case-insensitive rules.
- Missing `devices` means all devices.
- Deny precedence.
- No matching allow rule.
- API failure/no sessions/ambiguous sessions.
- High and medium session confidence.
- Stale medium-session behavior.
- Minrate insertion/update/suffix/unit parsing.
- Software filter rewrite.
- VAAPI/QSV filter rewrite.
- `filter_complex` bail.
- Unsupported hardware bail.
- Profile 5 probe and fail-closed behavior.
- P7.6/P8.1/HDR10 probe allow behavior.
- Final `execv()` argv integration.

## Packaging workflow notes

Build artifacts are ignored:

```text
pkg/
src/
*.pkg.tar.*
```

Checksums are intentionally `SKIP` during active local development. Replace them with real source checksums before publishing a stable/AUR package.

Increment `pkgrel` for package-only/source revisions that retain `pkgver=0.1.0`. It is currently `10`.

The package currently uses local source files, not a remote tagged tarball. A publishable PKGBUILD should eventually use a stable repository URL/tag and a non-empty `url` field.

## Security notes

- Never commit `/etc/jellyfin/shim.json` or a real API key.
- The example key must remain a placeholder.
- The API key is sent only to the configured Jellyfin URL using `X-Emby-Token`.
- The default URL is loopback HTTP. If changed to a remote host, use an appropriate trusted HTTPS endpoint.
- Config permissions should remain restrictive (`0640`, readable by Jellyfin).
- Full argv logging reveals media paths.
- Do not include the API key in logs or exceptions.
- Fail closed for HDR rewriting when identity/source capability is uncertain.

## Design decisions that should be preserved

- Blocking decision before `execv()`, not asynchronous discovery.
- One real FFmpeg execution through `os.execv()`.
- Minrate behavior independent from HDR allow/deny.
- Access rules case-insensitive.
- Deny rules override allow rules.
- Unsupported/ambiguous HDR rewrites fail closed.
- `filter_complex` remains passthrough until explicitly implemented.
- No arbitrary fixed-nit tonemapping in HDR-preservation mode.
- JSON owns operational configuration; Python does not duplicate normal defaults.
- Emergency real FFmpeg path is the sole intentional deployment fallback.
- No obsolete helper subprocess.

## Immediate recommended work order

1. Capture actual `ffprobe -show_streams -show_frames`/side-data JSON for representative HDR10, HDR10+, P5, P7.6, P8.1, P8.4, and HLG samples.
2. Define source-luminance metadata precedence for incompatible-HDR-to-HDR conversion; do not use a universal fixed-nit target.
3. Decide whether P5 should remain passthrough/SDR or use a hybrid `tonemapx=tonemap=none:apply_dovi=1` conversion.
4. Add committed automated tests for config, decisions, and both rewrite paths.
5. Improve medium-confidence session matching/stale-session policy.
6. Validate output files with ffprobe, including pixel format, profile, transfer, primaries, matrix, range, mastering display metadata, and absence/presence of Dolby Vision side data as intended.
7. Test subtitle burn-in separately before considering `filter_complex` support.
8. Add a project license and publication-ready package metadata.

## Output validation checklist

For an HDR-preserving result, inspect a generated segment or assembled output with the Jellyfin ffprobe:

```bash
/usr/lib/jellyfin-ffmpeg/ffprobe -hide_banner -show_streams -show_frames \
  -select_streams v:0 -of json /path/to/output
```

Expected baseline signals:

```text
codec_name=hevc
profile=Main 10
pix_fmt=yuv420p10le or hardware-equivalent encoded Main10
color_space=bt2020nc
color_transfer=smpte2084
color_primaries=bt2020
color_range=tv
```

Do not assume metadata labels alone prove correct pixels. Profile 5 is the key example where simply setting these labels is insufficient.

## Final caution

The current version is a useful working checkpoint with a fail-closed source gate, not a general incompatible-HDR converter. It has been demonstrated on an HDR10-compatible DV Profile 7.6 sample and on the server's Intel VAAPI/QSV path. Profile 5 is currently detected and denied rather than converted.

## Post-baseline safety-probe update

The source probe runs only for recognized HDR-to-SDR command shapes, including Jellyfin's Profile 5 OpenCL graph. It invokes configured ffprobe with stream/header-only JSON fields and a strict timeout. On the local P7.6 sample it completed in approximately 0.05 seconds.

Current source outcomes:

```text
Plain HEVC 10-bit BT.2020/PQ HDR10                         -> allow
DV profile 7/8 with present BT.2020/PQ HDR10 base layer   -> allow
DV Profile 5                                               -> deny
DV without base layer                                      -> deny
HLG/non-PQ/unknown source                                   -> deny
Probe timeout/error/malformed response                      -> deny
```

For the actual Profile 5/OpenCL sample, the intended log is:

```text
SOURCE_PROBE:
  - DECISION: DENY reason='Dolby Vision Profile 5 has no HDR10 fallback'
HDR_TO_HDR:
  - BAIL: source safety probe did not allow HDR preservation: Dolby Vision Profile 5 has no HDR10 fallback
```

The probe is intentionally evaluated before the unsupported-hardware bail so Profile 5 failures report the source-format reason. The OpenCL pipeline itself is not yet rewritable.

`--check-config` prints sanitized config-load state without launching FFmpeg or exposing the API key:

```bash
sudo -u jellyfin /usr/bin/jellyfin-ffmpeg-shim --check-config
```

Missing or malformed config uses both emergency fallbacks:

```text
FFmpeg: /usr/lib/jellyfin-ffmpeg/ffmpeg
Log:    /var/log/jellyfin/jellyfin-ffmpeg-shim.log
```

The shim reports one log-write failure to stderr so Jellyfin's FFmpeg log captures it instead of failing silently.

Future incompatible-HDR conversion policy:

- DV Profile 5 to HDR10 requires Dolby Vision reshaping, not arbitrary peak compression.
- HDR10+ to HDR10 should normally preserve the HDR10 base and static metadata while dropping unsupported dynamic metadata.
- HLG/DV 8.4 to PQ requires a real transfer conversion driven by source/reference metadata.
- Preserve source luminance intent and metadata when defensible; do not reintroduce a global 400-nit or 1000-nit target.

## Profile 5 to HDR10 implementation (uncommitted, pkgrel 15)

Profile 5 is now allowed only when ffprobe verifies HEVC 10-bit video plus both
an RPU and base layer. The source decision sets
`conversion_mode=dovi_profile5_to_hdr10`. This mode is intentionally distinct
from preserving a Profile 7/8 HDR10-compatible base layer.

The supported Jellyfin command shape is its VAAPI decode/OpenCL SDR/QSV encode
pipeline. The shim rewrites the existing OpenCL filter in place to:

```text
hwmap=derive_device=opencl:mode=read,
tonemap_opencl=format=p010:apply_dovi=true:tonemap=none:peak=0:t=smpte2084:m=bt2020:p=bt2020:r=tv,
hwmap=derive_device=qsv:mode=write:reverse=1:extra_hw_frames=16,format=qsv
```

Output is forced to QSV Main10 and tagged limited-range BT.2020/PQ. `peak=0`
is deliberate: no fixed luminance target is imposed, and the DV RPU reshaping
produces absolute-PQ HDR10 pixels. The original CPU hybrid path worked but was
replaced by this zero-copy OpenCL path. With Jellyfin idle, two 300-frame tests
(default and `tradeoff=enabled`) both processed 12.34 seconds of the Murderbot
sample in about 9.49 seconds (`1.31x`). Since the tradeoff option had no
measurable benefit, it is not enabled. A prior encoded result probed as Main10,
yuv420p10le, tv, bt2020nc, bt2020/smpte2084.

Known limitations:

- DV RPU/dynamic metadata is not retained in the HDR10 output.
- QSV output currently has correct PQ/color signaling but no static mastering
  display or MaxCLL/MaxFALL side data. Do not invent these values from one
  frame. The sample's first decoded RPU reported `source_max_pq=3079`, roughly
  1000 nits, but this is not hardcoded and other titles can differ.
- DV reshaping shares the iGPU's decode/compute/encode resources. Concurrent
  playback/transcoding reduced the same benchmark to roughly `0.94x`.
- Other Profile 5 command/filter shapes fail closed.

## Hardware backend architecture (uncommitted, pkgrel 17)

Hardware selection is derived exclusively from each FFmpeg argv, not from the
host GPU or a configured vendor assumption. `detect_hardware_backend()`
classifies Intel QSV, vendor-neutral VAAPI, NVIDIA CUDA/NVENC, AMD AMF, Vulkan
Video, Apple VideoToolbox, unknown hardware, and software commands.

Only the previously working Intel QSV behavior is registered in
`HARDWARE_BACKEND_REWRITERS`. No new AMD, NVIDIA, native VAAPI, Vulkan, or
VideoToolbox rewrite support was added. Detected backends without a registered
handler log their backend identity and pass through unchanged. Future support
should be added as a backend handler rather than by adding vendor conditions to
`rewrite_hdr_to_hdr()`.

Backend metadata is kept in `HARDWARE_BACKENDS`; it is descriptive and does not
enable behavior. Intel-specific functions are explicitly named
`rewrite_intel_qsv_*`. The generic flow performs source/client safety decisions
and then dispatches through `rewrite_hardware_backend()`.

The Intel backend does not encode a GPU model, PCI ID, render node, driver name,
or generation. Supported argv shapes are named in
`HARDWARE_PIPELINE_VARIANTS`, with explicit capability requirements (P010
filtering/mapping, OpenCL DV reshaping where applicable, and QSV Main10 encode).
The shim matches the graph Jellyfin selected; it does not independently select
hardware. Frame-pool sizes such as `extra_hw_frames` are preserved from the
incoming Jellyfin graph rather than hardcoded from the development host.

Regression tests are in `tests/test_hardware_backends.py`. They verify backend
detection, fail-closed passthrough for unimplemented families, software x265
classification even when Jellyfin initializes unused devices, and preservation
of the existing Intel HDR/DV graph rewrites and incoming frame-pool sizes.

# OmniFetch

**OmniFetch** is a terminal-first, multi-engine media downloader designed to run locally in Android's Termux environment.

Paste one URL. OmniFetch probes the installed engines, shows which ones recognize it, ranks usable options, then downloads with the selected engine. If an automatic download fails, it can fall back to another engine that passed its probe.

## Engines

| Engine | What it is used for | How it is integrated |
|---|---|---|
| yt-dlp | General video/audio extraction across thousands of sites | Local CLI |
| Streamlink | Supported live streams and stream sources | Local CLI |
| gallery-dl | Media galleries and supported gallery sites | Local CLI |
| aria2 | Direct HTTP(S) file downloads | Local CLI |
| Cobalt | Alternative extraction for Cobalt-supported services | Optional, user-configured Cobalt API |

Cobalt is disabled until you configure an instance you own or are authorized to use. The Cobalt project explicitly says its hosted API is protected and is not intended for use by unrelated projects without permission. See [Cobalt's API documentation](https://github.com/imputnet/cobalt/blob/main/docs/api.md).

OmniFetch does not bypass DRM, paywalls, private-content access controls, or service restrictions. Only download content you are authorized to save.

## Install in Termux

Use a current Termux build from a trusted distribution source. Then run:

```bash
pkg update && pkg upgrade
pkg install git python python-pip ffmpeg aria2
termux-setup-storage
git clone https://github.com/therealgudperson/omnifetch.git "$HOME/OmniFetch"
cd "$HOME/OmniFetch"
bash install-termux.sh
```

The installer installs the Python-based extraction tools, creates the `omnifetch` command in Termux's executable path, and leaves the source in `~/OmniFetch`.

On Termux, Streamlink's `lxml` dependency may need native compilation. The installer includes `build-essential`, `libxml2`, and `libxslt` for this. If an earlier install attempt failed before this fix, update the checkout and rerun the installer:

```bash
cd "$HOME/OmniFetch"
git pull
bash install-termux.sh
```

If you still see an `lxml` build error, install the native prerequisites manually and retry:

```bash
pkg install build-essential libxml2 libxslt
python -m pip install --no-cache-dir --upgrade lxml
python -m pip install --upgrade streamlink
```

The storage prompt creates standard links under `~/storage`. The default download folder is `~/storage/downloads/OmniFetch` when available; otherwise OmniFetch uses `~/OmniFetch/downloads`.

## Usage

Probe a URL without downloading:

```bash
omnifetch probe "https://example.com/video"
```

Probe and then interactively choose an engine:

```bash
omnifetch "https://example.com/video"
```

Download using the automatic engine ranking and fallback:

```bash
omnifetch download "https://example.com/video" --yes
```

Force a particular engine:

```bash
omnifetch download "https://example.com/video" --engine yt-dlp
omnifetch download "https://example.com/video" --engine streamlink
omnifetch download "https://example.com/gallery" --engine gallery-dl
omnifetch download "https://example.com/file.mp4" --engine aria2
```

List engines and check the installation:

```bash
omnifetch engines
omnifetch doctor
bash test-termux.sh
```

The test runner checks Python syntax and runs the local unit tests. It does not make network requests or download media.

Set a different output folder:

```bash
omnifetch config set output-dir "$HOME/storage/movies/OmniFetch"
```

Update the Python extraction tools:

```bash
python -m pip install --upgrade "yt-dlp[default]" streamlink gallery-dl
```

## Optional Cobalt integration

OmniFetch does **not** silently use a public Cobalt server. Configure an instance you operate or have permission to access:

```bash
omnifetch config set cobalt-api "https://your-cobalt-instance.example/"
```

If the instance requires an API key or bearer token, provide the complete Authorization header value through the environment:

```bash
export OMNIFETCH_COBALT_AUTH="Api-Key YOUR_TOKEN"
# or: export OMNIFETCH_COBALT_AUTH="Bearer YOUR_TOKEN"
```

Keep credentials private. Do not commit them to this repository or paste them into bug reports.

## How automatic selection works

1. Validate the URL and reject non-HTTP(S) schemes.
2. Probe available engines concurrently with per-engine timeouts.
3. Distinguish engines that resolved usable media from engines that only recognized the URL; report plugin-only matches separately.
4. Rank only engines that resolved usable media, using the media hints returned by their probes.
5. Download with the selected engine.
6. In automatic mode, move to the next probe-positive engine if a download fails.

A Streamlink plugin match alone is not considered a usable extraction path. OmniFetch additionally asks Streamlink to resolve a stream URL; if that fails, the engine is reported as `PLUGIN MATCH` and excluded from automatic selection. A probe is still not a download guarantee: websites change, signed URLs expire, network conditions vary, and some services require authentication. OmniFetch reports failures instead of claiming universal support.

## Project status

This is the first Termux CLI foundation. The initial release focuses on engine discovery, metadata probes, automatic ranking, fallback, direct downloads, and straightforward terminal operation. It does not include a background daemon, GUI, browser extension, or DRM handling.

## License

MIT. See [LICENSE](LICENSE).

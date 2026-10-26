# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

"eXM Media": a single-file Tkinter desktop GUI that wraps the `yt-dlp` CLI (with `ffmpeg` for conversion and section extraction) to download audio, video or thumbnails from a URL. No third-party Python packages are used. Only the standard library is needed, plus `yt-dlp` and `ffmpeg` on `PATH`.

- `media_downloader.py`: the whole app.
- `icons/exm-media.png`: the app icon. The desktop entry refers to it by absolute path.

## Running

```bash
python3 media_downloader.py
```

There is no build step, test suite or linter config. The app is installed outside this directory:
- `~/.local/bin/media-downloader` is a bash wrapper that runs `python3 ~/Applications/media-downloader/media_downloader.py`.
- `~/.local/share/applications/media-downloader.desktop` is the launcher entry ("EXM Media").

Renaming or moving `media_downloader.py` or the icon breaks both of these.

## Architecture (media_downloader.py)

Everything lives in the `MediaDownloader` class plus a few pure helpers (`time_to_seconds`, `seconds_to_time`, `valid_url`, `safe_filename`).

**Threading model:** blocking work runs in daemon threads: `fetch_chapters` runs `yt-dlp --dump-single-json` and `download` streams output from `yt-dlp` via `Popen`. Worker threads never touch Tk widgets. They push `(event, value)` tuples onto `self.events` (a `queue.Queue`), and `process_events` drains that queue on the Tk main loop every 100 ms via `root.after`. Event types are `log`, `progress`, `status`, `chapters`, `chapter_error`, `done` and `failed`. Any new background work should follow this pattern. The `running` and `loading` flags guard against starting operations at the same time.

**Download flow:** `start_download` validates the inputs (URL, folder, binaries, format/mode/thumbnail compatibility, time range or chapter selection) on the main thread. `build_command` then turns the choices into a `yt-dlp` argv. Notable flags: `--ignore-config`, `--no-overwrites`, `--windows-filenames`, `--newline` (needed for line-by-line progress parsing), `--download-sections` for time ranges (`*HH:MM:SS-HH:MM:SS`) and chapters (an anchored, case-insensitive, `re.escape`d title regex), and `--no-playlist` for any mode except "Full video / playlist".

**Progress parsing:** `PERCENT_RE` matches yt-dlp's `[download] NN%` lines. For section downloads, ffmpeg's `time=` output (`TIME_RE`) is converted to a percentage using `self.current_duration`. Postprocessor tags (`[ExtractAudio]`, `[Merger]`, etc.) update the status label.

**Chapters:** "Load Chapters" fetches metadata into `self.chapters`, a dict keyed by display label, tied to `self.chapters_url`. Editing the URL field clears the chapters through a trace on `self.url`, and results that come back for a URL that is no longer current are ignored.

**UI options are matched by their display strings.** `FORMATS`, `AUDIO`, `MODES` and `THUMBNAILS` are compared as literal strings throughout validation and `build_command`, so renaming a label means updating every comparison. `change_mode` finds where to insert the mode-specific frames by searching for the label whose text is "Thumbnail Options". Renaming that label silently breaks the mode switching.

**Branding:** the TigerMind palette constants (`TEAL`, `LAVENDER`, `RED`, `DARK`, `BG`, ...) and the named ttk styles (`Accent.TButton`, `Secondary.TButton`, `Tiger.Horizontal.TProgressbar`, ...) are defined in `create_styles` on the `clam` theme.

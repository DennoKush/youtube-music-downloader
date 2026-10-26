#!/usr/bin/env python3

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from urllib.parse import urlparse

APP_TITLE = "eXM Media"

# TigerMind brand colors
TEAL = "#1FCECB"
LAVENDER = "#CCCCFF"
RED = "#CF1F22"
DARK = "#1F2430"
WHITE = "#FFFFFF"
BG = "#F6F7FC"
MUTED = "#6B7280"

FORMATS = [
    "MP3", "M4A", "OPUS", "WAV", "FLAC",
    "MP4", "WEBM", "Thumbnail only"
]
AUDIO = {"MP3", "M4A", "OPUS", "WAV", "FLAC"}
MODES = [
    "Full video / playlist",
    "Time range",
    "Named chapter"
]
THUMBNAILS = [
    "None",
    "Embed as cover art",
    "Save thumbnail image",
    "Embed and save image"
]

PERCENT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
TIME_RE = re.compile(r"time=(\d+:\d{2}:\d{2}(?:\.\d+)?)")


def seconds_to_time(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def time_to_seconds(value):
    value = value.strip()
    if not value:
        return None

    parts = value.split(":")
    if len(parts) > 3 or not all(p.isdigit() for p in parts):
        raise ValueError("Use SS, MM:SS or HH:MM:SS")

    if len(parts) > 1 and any(int(p) >= 60 for p in parts[1:]):
        raise ValueError("Minutes and seconds must be below 60")

    result = 0
    for part in parts:
        result = result * 60 + int(part)
    return result


def valid_url(url):
    parsed = urlparse(url)
    return (
        parsed.scheme in ("http", "https")
        and bool(parsed.netloc)
    )


def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "download"


class MediaDownloader:

    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("800x790")
        self.root.minsize(640, 620)

        self.url = tk.StringVar()
        self.format = tk.StringVar(value="MP3")
        self.folder = tk.StringVar(value=os.getcwd())
        self.mode = tk.StringVar(value=MODES[0])
        self.start = tk.StringVar()
        self.end = tk.StringVar()
        self.chapter = tk.StringVar()
        self.thumbnail = tk.StringVar(value="None")
        self.status = tk.StringVar(value="Ready")
        self.percent = tk.StringVar(value="0%")

        self.chapters = {}
        self.chapters_url = None
        self.events = queue.Queue()
        self.running = False
        self.loading = False
        self.process = None
        self.cancelled = False
        self.current_duration = None

        self.create_styles()
        self.build_interface()
        self.change_mode()

        self.url.trace_add(
            "write", lambda *_: self.invalidate_chapters()
        )

        self.root.after(100, self.process_events)

    def create_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        self.root.configure(bg=BG)

        style.configure(
            ".", background=BG, foreground=DARK,
            fieldbackground=WHITE,
            font=("Sans", 10)
        )
        style.configure("Main.TFrame", background=BG)

        style.configure(
            "Title.TLabel",
            background=BG, foreground=DARK,
            font=("Sans", 22, "bold")
        )
        style.configure(
            "Section.TLabel",
            background=BG, foreground=DARK,
            font=("Sans", 11, "bold")
        )
        style.configure(
            "Field.TLabel",
            background=BG, foreground=DARK
        )
        style.configure(
            "Hint.TLabel",
            background=BG, foreground=MUTED,
            font=("Sans", 9)
        )
        style.configure(
            "Status.TLabel",
            background=BG, foreground=DARK,
            font=("Sans", 10, "bold")
        )

        style.configure(
            "TEntry", padding=6,
            fieldbackground=WHITE
        )
        style.configure(
            "TCombobox", padding=6,
            fieldbackground=WHITE,
            background=WHITE
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", WHITE)],
            selectbackground=[("readonly", WHITE)],
            selectforeground=[("readonly", DARK)]
        )

        style.configure(
            "Accent.TButton",
            background=TEAL, foreground=DARK,
            padding=(12, 10),
            borderwidth=0,
            font=("Sans", 11, "bold")
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", "#9ADFDB"),
                ("pressed", RED),
                ("active", "#18B9B5")
            ],
            foreground=[
                ("disabled", MUTED),
                ("active", DARK)
            ]
        )

        style.configure(
            "Secondary.TButton",
            background=LAVENDER, foreground=DARK,
            padding=(12, 8),
            borderwidth=0,
            font=("Sans", 10, "bold")
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("disabled", "#E5E5F5"),
                ("active", "#B8B8F2")
            ]
        )

        style.configure(
            "Tiger.Horizontal.TProgressbar",
            troughcolor=LAVENDER,
            background=TEAL,
            bordercolor=LAVENDER,
            lightcolor=TEAL,
            darkcolor=TEAL,
            thickness=18
        )

    def build_interface(self):
        frame = ttk.Frame(
            self.root, padding=20,
            style="Main.TFrame"
        )
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, text=APP_TITLE,
            style="Title.TLabel"
        ).pack(anchor="w", pady=(0, 14))

        ttk.Label(
            frame, text="Video or Playlist URL",
            style="Field.TLabel"
        ).pack(anchor="w")

        ttk.Entry(
            frame, textvariable=self.url
        ).pack(fill="x", pady=(4, 10))

        ttk.Label(
            frame, text="Download Format",
            style="Field.TLabel"
        ).pack(anchor="w")

        self.format_box = ttk.Combobox(
            frame, textvariable=self.format,
            values=FORMATS, state="readonly"
        )
        self.format_box.pack(fill="x", pady=(4, 10))

        ttk.Label(
            frame, text="Destination Folder",
            style="Field.TLabel"
        ).pack(anchor="w")

        folder_row = ttk.Frame(frame)
        folder_row.pack(fill="x", pady=(4, 10))

        ttk.Entry(
            folder_row, textvariable=self.folder
        ).pack(side="left", fill="x", expand=True)

        ttk.Button(
            folder_row, text="Browse",
            style="Secondary.TButton",
            command=self.choose_folder
        ).pack(side="left", padx=(8, 0))

        ttk.Label(
            frame, text="Download Mode",
            style="Section.TLabel"
        ).pack(anchor="w", pady=(4, 4))

        self.mode_box = ttk.Combobox(
            frame, textvariable=self.mode,
            values=MODES, state="readonly"
        )
        self.mode_box.pack(fill="x", pady=(0, 8))
        self.mode_box.bind(
            "<<ComboboxSelected>>",
            lambda event: self.change_mode()
        )

        # Time range controls
        self.time_frame = ttk.Frame(frame)

        times = ttk.Frame(self.time_frame)
        times.pack(fill="x")

        left = ttk.Frame(times)
        left.pack(
            side="left", fill="x",
            expand=True, padx=(0, 8)
        )
        ttk.Label(
            left, text="Start Time"
        ).pack(anchor="w")
        ttk.Entry(
            left, textvariable=self.start
        ).pack(fill="x", pady=(4, 0))

        right = ttk.Frame(times)
        right.pack(side="left", fill="x", expand=True)
        ttk.Label(
            right, text="End Time"
        ).pack(anchor="w")
        ttk.Entry(
            right, textvariable=self.end
        ).pack(fill="x", pady=(4, 0))

        ttk.Label(
            self.time_frame,
            text="Example: 00:04:37 to 00:09:39",
            style="Hint.TLabel"
        ).pack(anchor="w", pady=(5, 0))

        # Named chapter controls
        self.chapter_frame = ttk.Frame(frame)

        chapter_row = ttk.Frame(self.chapter_frame)
        chapter_row.pack(fill="x")

        self.load_button = ttk.Button(
            chapter_row,
            text="Load Chapters",
            style="Secondary.TButton",
            command=self.load_chapters
        )
        self.load_button.pack(
            side="left", pady=(0, 6)
        )

        ttk.Label(
            chapter_row,
            text="Select a song from the video",
            style="Hint.TLabel"
        ).pack(side="left", padx=12)

        self.chapter_box = ttk.Combobox(
            self.chapter_frame,
            textvariable=self.chapter,
            state="readonly"
        )
        self.chapter_box.pack(fill="x")

        ttk.Label(
            self.chapter_frame,
            text="The selected chapter will be saved "
                 "using its song title.",
            style="Hint.TLabel"
        ).pack(anchor="w", pady=(5, 0))

        ttk.Label(
            frame, text="Thumbnail Options",
            style="Section.TLabel"
        ).pack(anchor="w", pady=(12, 4))

        self.thumbnail_box = ttk.Combobox(
            frame, textvariable=self.thumbnail,
            values=THUMBNAILS, state="readonly"
        )
        self.thumbnail_box.pack(fill="x", pady=(0, 14))

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x", pady=(0, 12))

        self.download_button = ttk.Button(
            button_row, text="Download",
            style="Accent.TButton",
            command=self.start_download
        )
        self.download_button.pack(
            side="left", fill="x", expand=True
        )

        self.cancel_button = ttk.Button(
            button_row, text="Cancel",
            style="Secondary.TButton",
            command=self.cancel_download,
            state="disabled"
        )
        self.cancel_button.pack(
            side="left", padx=(8, 0)
        )

        progress_row = ttk.Frame(frame)
        progress_row.pack(fill="x")

        ttk.Label(
            progress_row, text="Download Progress"
        ).pack(side="left")

        ttk.Label(
            progress_row,
            textvariable=self.percent,
            style="Status.TLabel"
        ).pack(side="right")

        self.progress = ttk.Progressbar(
            frame, maximum=100,
            mode="determinate",
            style="Tiger.Horizontal.TProgressbar"
        )
        self.progress.pack(
            fill="x", pady=(6, 8)
        )

        ttk.Label(
            frame, textvariable=self.status,
            style="Status.TLabel"
        ).pack(anchor="w", pady=(0, 8))

        self.log = scrolledtext.ScrolledText(
            frame, height=8,
            wrap="word",
            state="disabled",
            bg=WHITE, fg=DARK,
            insertbackground=DARK,
            font=("Monospace", 9)
        )
        self.log.pack(fill="both", expand=True)

    def change_mode(self):
        self.time_frame.pack_forget()
        self.chapter_frame.pack_forget()

        mode = self.mode.get()

        # Use the existing pack order by placing
        # controls before the thumbnail heading.
        # Find that label once by its visible text.
        parent = self.time_frame.master
        target = None
        for child in parent.winfo_children():
            if (
                isinstance(child, ttk.Label)
                and child.cget("text") == "Thumbnail Options"
            ):
                target = child
                break

        if mode == "Time range":
            self.time_frame.pack(
                fill="x", pady=(0, 4),
                before=target
            )
        elif mode == "Named chapter":
            self.chapter_frame.pack(
                fill="x", pady=(0, 4),
                before=target
            )

    def invalidate_chapters(self):
        self.chapters = {}
        self.chapters_url = None
        self.chapter.set("")
        self.chapter_box.configure(values=[])

    def choose_folder(self):
        folder = filedialog.askdirectory(
            initialdir=self.folder.get()
        )
        if folder:
            self.folder.set(folder)

    def write_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def reset_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def load_chapters(self):
        if self.running or self.loading:
            return

        url = self.url.get().strip()
        if not valid_url(url):
            messagebox.showerror(
                "Invalid URL", "Enter a valid video URL."
            )
            return

        binary = shutil.which("yt-dlp")
        if not binary:
            messagebox.showerror(
                "Missing yt-dlp",
                "yt-dlp could not be found."
            )
            return

        self.loading = True
        self.load_button.configure(state="disabled")
        self.status.set("Loading chapters...")
        self.invalidate_chapters()

        threading.Thread(
            target=self.fetch_chapters,
            args=(binary, url),
            daemon=True
        ).start()

    def fetch_chapters(self, binary, url):
        command = [
            binary, "--no-playlist",
            "--dump-single-json", "--no-warnings",
            url
        ]

        try:
            result = subprocess.run(
                command, capture_output=True,
                text=True, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(
                    result.stderr.strip()
                    or "Unable to load chapters."
                )

            metadata = json.loads(result.stdout)
            chapters = metadata.get("chapters") or []

            self.events.put(
                ("chapters", (url, chapters))
            )
        except Exception as error:
            self.events.put(
                ("chapter_error", str(error))
            )

    def start_download(self):
        if self.running or self.loading:
            return

        url = self.url.get().strip()
        folder = Path(
            self.folder.get()
        ).expanduser()

        if not valid_url(url):
            messagebox.showerror(
                "Invalid URL",
                "Please enter a valid URL."
            )
            return

        if not folder.is_dir():
            messagebox.showerror(
                "Invalid Folder",
                "Please select an existing folder."
            )
            return

        binary = shutil.which("yt-dlp")
        if not binary:
            messagebox.showerror(
                "Missing yt-dlp",
                "yt-dlp was not found."
            )
            return

        if not shutil.which("ffmpeg"):
            messagebox.showerror(
                "Missing FFmpeg",
                "Please install FFmpeg."
            )
            return

        mode = self.mode.get()
        output_format = self.format.get()
        thumbnail = self.thumbnail.get()

        if output_format == "Thumbnail only":
            if mode != "Full video / playlist":
                messagebox.showerror(
                    "Invalid Mode",
                    "Choose Full video / playlist "
                    "for thumbnail-only downloads."
                )
                return

        if (
            thumbnail in (
                "Embed as cover art",
                "Embed and save image"
            )
            and output_format not in (
                "MP3", "M4A", "FLAC", "MP4"
            )
        ):
            messagebox.showerror(
                "Unsupported Format",
                "Embedding thumbnails is supported "
                "here for MP3, M4A, FLAC and MP4."
            )
            return

        start = end = None
        selected_chapter = None
        duration = None

        if mode == "Time range":
            try:
                start = time_to_seconds(self.start.get())
                end = time_to_seconds(self.end.get())

                if start is None and end is None:
                    raise ValueError(
                        "Enter at least one time boundary."
                    )

                if end is not None and end <= (start or 0):
                    raise ValueError(
                        "End time must be after start time."
                    )

                if start is not None and end is not None:
                    duration = end - start

            except ValueError as error:
                messagebox.showerror(
                    "Invalid Time", str(error)
                )
                return

        elif mode == "Named chapter":
            if (
                not self.chapters
                or self.chapters_url != url
                or self.chapter.get() not in self.chapters
            ):
                messagebox.showerror(
                    "Chapter Required",
                    "Load chapters and select a song first."
                )
                return

            selected_chapter = self.chapters[
                self.chapter.get()
            ]
            start = selected_chapter["start_time"]
            end = selected_chapter["end_time"]
            if end is not None:
                duration = end - start

        self.running = True
        self.cancelled = False
        self.download_button.configure(state="disabled")
        self.load_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.progress["value"] = 0
        self.percent.set("0%")
        self.status.set("Preparing download...")
        self.current_duration = duration
        self.reset_log()

        threading.Thread(
            target=self.download,
            args=(
                binary, url, str(folder),
                output_format, thumbnail,
                mode, start, end, selected_chapter
            ),
            daemon=True
        ).start()

    def cancel_download(self):
        if not self.running or self.cancelled:
            return

        self.cancelled = True
        self.cancel_button.configure(state="disabled")
        self.status.set("Cancelling...")
        self.write_log("Cancelling download...")

        # If the worker has not started yt-dlp yet, it
        # checks self.cancelled right after Popen.
        process = self.process
        self.stop_process(process, signal.SIGTERM)

        # Force kill if yt-dlp or ffmpeg ignore SIGTERM.
        self.root.after(
            5000,
            lambda: self.stop_process(
                process, signal.SIGKILL
            )
        )

    def stop_process(self, process, sig):
        if process is None or process.poll() is not None:
            return

        # yt-dlp runs in its own process group, so this
        # also stops the ffmpeg children it spawned.
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def build_command(
        self, binary, url, folder,
        output_format, thumbnail,
        mode, start, end, selected_chapter
    ):
        command = [
            binary, "--newline",
            "--ignore-config",
            "--no-overwrites",
            "--windows-filenames",
            "-P", folder,
        ]

        # Section modes must target one video.
        if mode != "Full video / playlist":
            command.append("--no-playlist")

        if selected_chapter:
            title = safe_filename(
                selected_chapter["title"]
            )
            template = (
                f"{title} [%(id)s].%(ext)s"
            )
        elif mode == "Time range":
            label = (
                f"Section {seconds_to_time(start or 0)}"
                f"-{seconds_to_time(end)}"
                if end is not None else
                f"Section from {seconds_to_time(start or 0)}"
            )
            template = (
                f"%(title).100B - "
                f"{safe_filename(label)} "
                f"[%(id)s].%(ext)s"
            )
        else:
            template = "%(title).180B [%(id)s].%(ext)s"

        command += ["-o", template]

        if output_format == "Thumbnail only":
            command += [
                "--skip-download",
                "--write-thumbnail"
            ]

        elif output_format in AUDIO:
            command += [
                "-f", "bestaudio/best",
                "-x",
                "--audio-format",
                output_format.lower(),
                "--audio-quality", "0"
            ]

        elif output_format == "MP4":
            command += [
                "-f",
                "bv*[ext=mp4]+ba[ext=m4a]/"
                "b[ext=mp4]/bv*+ba/b",
                "--merge-output-format", "mp4",
                "--recode-video", "mp4"
            ]

        elif output_format == "WEBM":
            command += [
                "-f", "bv*+ba/b",
                "--recode-video", "webm"
            ]

        if mode == "Named chapter":
            # Escape regex characters in the chapter title.
            chapter_regex = (
                "(?i)^"
                + re.escape(selected_chapter["title"])
                + "$"
            )
            command += [
                "--download-sections",
                chapter_regex
            ]

        elif mode == "Time range":
            beginning = seconds_to_time(start or 0)
            ending = (
                seconds_to_time(end)
                if end is not None else "inf"
            )
            command += [
                "--download-sections",
                f"*{beginning}-{ending}"
            ]

        if output_format != "Thumbnail only":
            if thumbnail in (
                "Embed as cover art",
                "Embed and save image"
            ):
                command.append("--embed-thumbnail")

            if thumbnail in (
                "Save thumbnail image",
                "Embed and save image"
            ):
                command.append("--write-thumbnail")

        command.append(url)
        return command

    def download(
        self, binary, url, folder,
        output_format, thumbnail,
        mode, start, end, selected_chapter
    ):
        command = self.build_command(
            binary, url, folder,
            output_format, thumbnail,
            mode, start, end, selected_chapter
        )

        recent_lines = []

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                start_new_session=True
            )
            self.process = process

            if self.cancelled:
                self.stop_process(process, signal.SIGTERM)

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                recent_lines.append(line)
                recent_lines = recent_lines[-30:]
                self.events.put(("log", line))

                match = PERCENT_RE.search(line)
                if match:
                    self.events.put((
                        "progress",
                        float(match.group(1))
                    ))

                # FFmpeg progress for section extraction.
                elif (
                    self.current_duration
                    and TIME_RE.search(line)
                ):
                    match = TIME_RE.search(line)
                    try:
                        elapsed = time_to_seconds(
                            match.group(1).split(".")[0]
                        )
                        progress = min(
                            99,
                            100 * elapsed /
                            self.current_duration
                        )
                        self.events.put((
                            "progress", progress
                        ))
                    except (ValueError, ZeroDivisionError):
                        pass

                if "[ExtractAudio]" in line:
                    self.events.put((
                        "status", "Converting audio..."
                    ))
                elif "[EmbedThumbnail]" in line:
                    self.events.put((
                        "status", "Embedding cover art..."
                    ))
                elif "[Merger]" in line:
                    self.events.put((
                        "status", "Merging streams..."
                    ))
                elif "[VideoConvertor]" in line:
                    self.events.put((
                        "status", "Converting video..."
                    ))

            code = process.wait()

            if self.cancelled:
                self.events.put(("cancelled", None))
            elif code == 0:
                self.events.put(("done", None))
            else:
                errors = [
                    line for line in recent_lines
                    if "ERROR:" in line
                ]
                detail = (
                    "\n".join(errors[-3:])
                    if errors else
                    "\n".join(recent_lines[-8:])
                )
                self.events.put((
                    "failed",
                    f"yt-dlp exited with code {code}\n{detail}"
                ))

        except Exception as error:
            if self.cancelled:
                self.events.put(("cancelled", None))
            else:
                self.events.put(("failed", str(error)))

        finally:
            self.process = None

    def process_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()

                if event == "log":
                    self.write_log(value)

                elif event == "chapters":
                    url, chapters = value
                    self.loading = False
                    self.load_button.configure(
                        state="normal"
                    )

                    # Ignore results for an old URL.
                    if url != self.url.get().strip():
                        continue

                    self.chapters = {}
                    self.chapters_url = url

                    for index, chapter in enumerate(
                        chapters, start=1
                    ):
                        title = chapter.get(
                            "title", f"Chapter {index}"
                        )
                        start = chapter.get("start_time")
                        end = chapter.get("end_time")

                        if start is None:
                            continue

                        time_label = seconds_to_time(start)
                        end_label = (
                            seconds_to_time(end)
                            if end is not None else "End"
                        )

                        label = (
                            f"{index:02d}. {title} "
                            f"({time_label} - {end_label})"
                        )

                        self.chapters[label] = {
                            "title": title,
                            "start_time": start,
                            "end_time": end
                        }

                    choices = list(self.chapters)
                    self.chapter_box.configure(
                        values=choices
                    )

                    if choices:
                        self.chapter.set(choices[0])
                        self.status.set(
                            f"Loaded {len(choices)} chapters"
                        )
                    else:
                        self.status.set(
                            "No chapters available"
                        )
                        messagebox.showinfo(
                            "No Chapters",
                            "This video does not expose "
                            "YouTube chapter metadata."
                        )

                elif event == "chapter_error":
                    self.loading = False
                    self.load_button.configure(
                        state="normal"
                    )
                    self.status.set("Chapter loading failed")
                    messagebox.showerror(
                        "Chapter Error", value
                    )

                elif event in ("progress", "status") and (
                    self.cancelled
                ):
                    continue

                elif event == "progress":
                    amount = max(0, min(100, value))
                    self.progress["value"] = amount
                    self.percent.set(f"{amount:.1f}%")
                    self.status.set("Downloading...")

                elif event == "status":
                    self.status.set(value)

                elif event in ("done", "failed", "cancelled"):
                    self.running = False
                    self.download_button.configure(
                        state="normal"
                    )
                    self.load_button.configure(
                        state="normal"
                    )
                    self.cancel_button.configure(
                        state="disabled"
                    )

                    if event == "cancelled":
                        self.progress["value"] = 0
                        self.percent.set("0%")
                        self.status.set("Download cancelled")
                        self.write_log(
                            "Download cancelled. Partial "
                            ".part files may remain in the "
                            "output folder."
                        )
                    elif event == "done":
                        self.progress["value"] = 100
                        self.percent.set("100%")
                        self.status.set(
                            "Download completed"
                        )
                        self.write_log(
                            "Download completed successfully."
                        )
                        messagebox.showinfo(
                            "eXM Media",
                            "Download completed successfully!"
                        )
                    else:
                        self.status.set("Download failed")
                        self.write_log(
                            f"ERROR: {value}"
                        )
                        messagebox.showerror(
                            "Download Failed",
                            value[:1200]
                        )

        except queue.Empty:
            pass

        self.root.after(100, self.process_events)


if __name__ == "__main__":
    root = tk.Tk()
    MediaDownloader(root)
    root.mainloop()

"""Extraction and download adapters.

All external programs are launched with argument arrays (never through a shell).
The module intentionally uses only the Python standard library.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import DownloadResult, ProbeResult, safe_filename


USER_AGENT = "OmniFetch/0.1.0 (+https://github.com/therealgudperson/omnifetch)"
DEFAULT_TIMEOUT = 35


def _which(command: str) -> str | None:
    return shutil.which(command)


def _run(command: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _last_error(proc: subprocess.CompletedProcess[str]) -> str:
    text = (proc.stderr or proc.stdout or "The engine exited without an error message.").strip()
    return text[-900:]


def _missing(name: str, command: str) -> ProbeResult:
    return ProbeResult(
        engine=name,
        status="MISSING",
        supported=False,
        confidence=0,
        message=f"{command} is not installed or is not on PATH.",
    )


class Engine:
    name = "engine"
    command = ""
    priority = 0

    def available(self) -> bool:
        return bool(_which(self.command))

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        raise NotImplementedError

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        raise NotImplementedError


class YtDlpEngine(Engine):
    name = "yt-dlp"
    command = "yt-dlp"
    priority = 100

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        executable = _which(self.command)
        if not executable:
            return _missing(self.name, self.command)

        try:
            proc = _run(
                [executable, "--dump-single-json", "--skip-download", "--no-warnings",
                 "--no-call-home", url],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(self.name, "ERROR", False, 0, f"Metadata probe timed out after {timeout}s.")

        if proc.returncode != 0:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, _last_error(proc))

        try:
            data = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            return ProbeResult(self.name, "ERROR", False, 0, "yt-dlp returned output that was not valid JSON.")

        metadata = {
            "title": data.get("title"),
            "extractor": data.get("extractor_key") or data.get("extractor"),
            "duration": data.get("duration"),
            "format_count": len(data.get("formats") or []),
            "live_status": data.get("live_status"),
            "is_live": bool(data.get("is_live") or data.get("live_status") == "is_live"),
            "is_playlist": data.get("_type") in {"playlist", "multi_video"},
            "entry_count": data.get("playlist_count") or data.get("n_entries"),
        }
        message = "yt-dlp recognized this URL."
        if metadata["title"]:
            message += f" Title: {metadata['title']}"
        return ProbeResult(self.name, "READY", True, 100, message, metadata)

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        executable = _which(self.command)
        if not executable:
            return DownloadResult(self.name, False, "yt-dlp is not installed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "--newline",
            "--no-warnings",
            "--no-call-home",
            "--paths", str(output_dir),
            "--output", "%(title).150B [%(id)s].%(ext)s",
            "--format", "bv*+ba/b",
            "--merge-output-format", "mkv",
            url,
        ]
        print(f"\nStarting yt-dlp. Output folder: {output_dir}")
        try:
            proc = subprocess.run(command, check=False)
        except KeyboardInterrupt:
            return DownloadResult(self.name, False, "Download interrupted by user.")
        except OSError as exc:
            return DownloadResult(self.name, False, str(exc))
        return DownloadResult(
            self.name, proc.returncode == 0,
            "yt-dlp finished successfully." if proc.returncode == 0 else f"yt-dlp exited with code {proc.returncode}.",
            str(output_dir) if proc.returncode == 0 else None,
        )


class StreamlinkEngine(Engine):
    name = "streamlink"
    command = "streamlink"
    priority = 75

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        executable = _which(self.command)
        if not executable:
            return _missing(self.name, self.command)

        try:
            proc = _run([executable, "--can-handle-url", url], timeout=timeout)
        except subprocess.TimeoutExpired:
            return ProbeResult(self.name, "ERROR", False, 0, f"Streamlink probe timed out after {timeout}s.")

        if proc.returncode != 0:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, _last_error(proc))

        return ProbeResult(
            self.name, "READY", True, 85,
            "Streamlink has a plugin that recognizes this URL.",
            {"plugin_match": True},
        )

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        executable = _which(self.command)
        if not executable:
            return DownloadResult(self.name, False, "Streamlink is not installed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"streamlink-{stamp}.ts"
        command = [executable, "--force", "--output", str(output_path), url, "best"]
        print(f"\nStarting Streamlink. Stop a live recording with Ctrl+C.")
        try:
            proc = subprocess.run(command, check=False)
        except KeyboardInterrupt:
            return DownloadResult(self.name, False, "Stream recording interrupted by user.", str(output_path))
        except OSError as exc:
            return DownloadResult(self.name, False, str(exc))
        success = proc.returncode == 0 and output_path.exists()
        return DownloadResult(
            self.name, success,
            "Streamlink finished successfully." if success else f"Streamlink exited with code {proc.returncode}.",
            str(output_path) if success else None,
        )


class GalleryDlEngine(Engine):
    name = "gallery-dl"
    command = "gallery-dl"
    priority = 65

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        executable = _which(self.command)
        if not executable:
            return _missing(self.name, self.command)

        try:
            proc = _run([executable, "--simulate", "--dump-json", url], timeout=timeout)
        except subprocess.TimeoutExpired:
            return ProbeResult(self.name, "ERROR", False, 0, f"gallery-dl probe timed out after {timeout}s.")

        if proc.returncode != 0:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, _last_error(proc))

        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, "gallery-dl returned no media items.")

        return ProbeResult(
            self.name, "READY", True, 78,
            f"gallery-dl recognized this URL ({len(lines)} item record(s) returned).",
            {"item_records": len(lines), "is_gallery": True},
        )

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        executable = _which(self.command)
        if not executable:
            return DownloadResult(self.name, False, "gallery-dl is not installed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        command = [executable, "--destination", str(output_dir), url]
        print(f"\nStarting gallery-dl. Output folder: {output_dir}")
        try:
            proc = subprocess.run(command, check=False)
        except KeyboardInterrupt:
            return DownloadResult(self.name, False, "Gallery download interrupted by user.")
        except OSError as exc:
            return DownloadResult(self.name, False, str(exc))
        return DownloadResult(
            self.name, proc.returncode == 0,
            "gallery-dl finished successfully." if proc.returncode == 0 else f"gallery-dl exited with code {proc.returncode}.",
            str(output_dir) if proc.returncode == 0 else None,
        )


class Aria2Engine(Engine):
    name = "aria2"
    command = "aria2c"
    priority = 50

    def _inspect(self, url: str, timeout: int) -> tuple[dict[str, Any] | None, str | None]:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        request = urllib.request.Request(url, headers=headers, method="HEAD")

        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in {405, 501}:
                return None, f"HTTP {exc.code}: {exc.reason}"
            request = urllib.request.Request(url, headers={**headers, "Range": "bytes=0-0"}, method="GET")
            try:
                response = urllib.request.urlopen(request, timeout=timeout)
            except Exception as range_exc:
                return None, str(range_exc)
        except Exception as exc:
            return None, str(exc)

        try:
            with response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                disposition = response.headers.get("Content-Disposition", "")
                parsed = Message()
                parsed["content-disposition"] = disposition
                filename = parsed.get_filename()
                length = response.headers.get("Content-Length")
                final_url = response.geturl()
                path_name = Path(urlsplit(final_url).path).name
                filename = filename or path_name
                is_media = (
                    content_type.startswith("video/")
                    or content_type.startswith("audio/")
                    or content_type in {"application/octet-stream", "application/mp4"}
                    or "attachment" in disposition.lower()
                )
                if not is_media:
                    return None, f"Direct response is {content_type or 'an unknown type'}, not an obvious media file."
                return {
                    "content_type": content_type,
                    "content_length": int(length) if length and length.isdigit() else None,
                    "filename": filename or None,
                    "final_url": final_url,
                }, None
        except Exception as exc:
            return None, str(exc)

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        executable = _which(self.command)
        if not executable:
            return _missing(self.name, self.command)

        metadata, error = self._inspect(url, timeout)
        if error:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, error)
        assert metadata is not None
        size = metadata.get("content_length")
        detail = f"Direct media URL detected ({metadata.get('content_type') or 'binary'}"
        if size:
            detail += f", {size:,} bytes"
        detail += ")."
        return ProbeResult(self.name, "READY", True, 60, detail, metadata)

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        executable = _which(self.command)
        if not executable:
            return DownloadResult(self.name, False, "aria2c is not installed.")

        output_dir.mkdir(parents=True, exist_ok=True)
        metadata = probe.metadata if probe else {}
        filename = safe_filename(metadata.get("filename") or Path(urlsplit(url).path).name, "direct-download.bin")
        command = [
            executable, "--continue=true", "--summary-interval=1",
            "--console-log-level=notice", "--max-connection-per-server=8",
            "--split=8", "--dir", str(output_dir), "--out", filename, url,
        ]
        print(f"\nStarting aria2: {filename}")
        try:
            proc = subprocess.run(command, check=False)
        except KeyboardInterrupt:
            return DownloadResult(self.name, False, "Direct download interrupted by user.", str(output_dir / filename))
        except OSError as exc:
            return DownloadResult(self.name, False, str(exc))
        output_path = output_dir / filename
        success = proc.returncode == 0 and output_path.exists()
        return DownloadResult(
            self.name, success,
            "aria2 finished successfully." if success else f"aria2 exited with code {proc.returncode}.",
            str(output_path) if success else None,
        )


class CobaltEngine(Engine):
    name = "cobalt"
    command = ""
    priority = 90

    def __init__(self, config: dict[str, Any]):
        self.api_base = str(config.get("cobalt_api") or "").strip().rstrip("/")
        self.auth = os.environ.get("OMNIFETCH_COBALT_AUTH", "").strip()

    def available(self) -> bool:
        if not self.api_base:
            return False
        parsed = urlsplit(self.api_base)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    def _prepare(self, url: str, timeout: int) -> tuple[dict[str, Any] | None, str | None]:
        if not self.available():
            return None, "Cobalt API is not configured."

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.auth:
            headers["Authorization"] = self.auth

        body = json.dumps({"url": url, "downloadMode": "auto", "videoQuality": "max"}).encode("utf-8")
        request = urllib.request.Request(self.api_base + "/", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = str(exc)
            return None, f"Cobalt API HTTP {exc.code}: {detail}"
        except Exception as exc:
            return None, f"Cobalt API request failed: {exc}"

        status = data.get("status")
        if status not in {"tunnel", "redirect", "picker"}:
            return None, f"Cobalt returned {status or 'an unknown status'}: {data.get('text') or data.get('error') or data}"
        return data, None

    def probe(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> ProbeResult:
        if not self.api_base:
            return ProbeResult(
                self.name, "DISABLED", False, 0,
                "Configure an authorized Cobalt API with: omnifetch config set cobalt-api URL",
            )
        data, error = self._prepare(url, timeout)
        if error:
            return ProbeResult(self.name, "UNSUPPORTED", False, 0, error)
        assert data is not None
        status = data.get("status")
        if status == "picker":
            choices = data.get("picker") or []
            return ProbeResult(
                self.name, "READY", bool(choices), 92,
                f"Cobalt returned {len(choices)} selectable media item(s).",
                {"cobalt_response": data, "picker_count": len(choices)},
            )
        return ProbeResult(
            self.name, "READY", True, 92,
            f"Cobalt prepared a {status} download.",
            {"cobalt_response": data, "filename": data.get("filename")},
        )

    def download(self, url: str, output_dir: Path, probe: ProbeResult | None = None) -> DownloadResult:
        if not self.api_base:
            return DownloadResult(self.name, False, "Cobalt API is not configured.")

        # Reuse the probe response when possible. Otherwise prepare a fresh one.
        data = (probe.metadata.get("cobalt_response") if probe else None)
        if not isinstance(data, dict):
            data, error = self._prepare(url, DEFAULT_TIMEOUT)
            if error:
                return DownloadResult(self.name, False, error)
        assert isinstance(data, dict)

        target_url = data.get("url")
        filename = data.get("filename")
        if data.get("status") == "picker":
            choices = data.get("picker") or []
            if not choices:
                return DownloadResult(self.name, False, "Cobalt returned an empty media picker.")
            video_choices = [item for item in choices if item.get("type") in {"video", "gif"}]
            choices = video_choices or choices
            chosen_index = 0
            if len(choices) > 1 and sys.stdin.isatty():
                print("\\nCobalt found multiple media items:")
                for index, item in enumerate(choices, start=1):
                    print(f"  {index}. {item.get('type', 'media')}")
                try:
                    entered = input("Choose item [1]: ").strip()
                    if entered.isdigit() and 1 <= int(entered) <= len(choices):
                        chosen_index = int(entered) - 1
                except (EOFError, KeyboardInterrupt):
                    print()
            chosen = choices[chosen_index]
            target_url = chosen.get("url")
            filename = chosen.get("filename") or filename
            if not filename:
                extension = {"video": ".mp4", "gif": ".gif", "photo": ".jpg"}.get(chosen.get("type"), ".bin")
                filename = f"cobalt-{chosen.get('type', 'media')}-{chosen_index + 1}{extension}"

        parsed = urlsplit(str(target_url or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return DownloadResult(self.name, False, "Cobalt did not return a valid HTTP(S) media URL.")

        output_dir.mkdir(parents=True, exist_ok=True)
        if not filename:
            filename = Path(parsed.path).name or "cobalt-download.bin"
        filename = safe_filename(filename)
        output_path = output_dir / filename

        request = urllib.request.Request(str(target_url), headers={"User-Agent": USER_AGENT})
        try:
            print(f"\nDownloading through Cobalt: {filename}")
            with urllib.request.urlopen(request, timeout=60) as response, output_path.open("wb") as output:
                shutil.copyfileobj(response, output)
        except KeyboardInterrupt:
            output_path.unlink(missing_ok=True)
            return DownloadResult(self.name, False, "Cobalt download interrupted by user.")
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            return DownloadResult(self.name, False, f"Cobalt media transfer failed: {exc}")

        if not output_path.exists() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            return DownloadResult(self.name, False, "Cobalt returned an empty file.")
        return DownloadResult(self.name, True, "Cobalt download finished successfully.", str(output_path))


def build_engines(config: dict[str, Any]) -> list[Engine]:
    """Return all supported adapters. Missing binaries are reported by probes."""
    return [
        YtDlpEngine(),
        CobaltEngine(config),
        StreamlinkEngine(),
        GalleryDlEngine(),
        Aria2Engine(),
    ]

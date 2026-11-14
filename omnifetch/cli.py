"""OmniFetch command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import __version__
from .engines import build_engines
from .models import ProbeResult, validate_url


COMMANDS = {"probe", "download", "engines", "doctor", "config", "--help", "-h", "--version"}


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "omnifetch" / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        print(f"Warning: could not read config at {path}; using defaults.", file=sys.stderr)
        return {}


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def default_output_dir() -> Path:
    termux_downloads = Path.home() / "storage" / "downloads"
    if termux_downloads.exists():
        return termux_downloads / "OmniFetch"
    return Path.home() / "OmniFetch" / "downloads"


def resolve_output_dir(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    raw = getattr(args, "output", None) or config.get("output_dir") or str(default_output_dir())
    return Path(raw).expanduser()


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omnifetch",
        description="Probe multiple media engines, compare support, and download with automatic fallback.",
        epilog="Paste a URL directly: omnifetch 'https://example.com/video'",
    )
    parser.add_argument("--version", action="version", version=f"OmniFetch {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    probe_parser = commands.add_parser("probe", help="Test installed engines against a URL without saving media.")
    probe_parser.add_argument("url")
    probe_parser.add_argument("--timeout", type=int, default=35, help="Per-engine probe timeout in seconds.")
    probe_parser.add_argument("--json", action="store_true", help="Print probe results as JSON.")

    download_parser = commands.add_parser("download", help="Probe engines and download with the best candidate.")
    download_parser.add_argument("url")
    download_parser.add_argument("-e", "--engine", default="auto",
                                 choices=["auto", "yt-dlp", "cobalt", "streamlink", "gallery-dl", "aria2"])
    download_parser.add_argument("-o", "--output", help="Output folder.")
    download_parser.add_argument("-y", "--yes", action="store_true", help="Skip engine-selection prompt.")
    download_parser.add_argument("--timeout", type=int, default=35, help="Per-engine probe timeout in seconds.")

    commands.add_parser("engines", help="Show available engines and their local requirements.")
    commands.add_parser("doctor", help="Check the Termux environment and configured engines.")

    config_parser = commands.add_parser("config", help="Read or update OmniFetch settings.")
    config_actions = config_parser.add_subparsers(dest="config_action", required=True)
    config_actions.add_parser("show", help="Show current settings.")
    set_parser = config_actions.add_parser("set", help="Set a setting.")
    set_parser.add_argument("key", choices=["output-dir", "cobalt-api"])
    set_parser.add_argument("value")

    return parser


def _style(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def print_results(results: list[ProbeResult]) -> None:
    print("\nEngine probe results")
    print("=" * 78)
    for result in results:
        if result.status == "READY":
            label = _style("READY", "32;1")
        elif result.status == "MISSING":
            label = _style("MISSING", "33;1")
        elif result.status == "DISABLED":
            label = _style("DISABLED", "2")
        elif result.status == "UNSUPPORTED":
            label = _style("NO MATCH", "31")
        else:
            label = _style(result.status, "33")
        print(f"{result.engine:<12} {label:<18} {result.message}")
    print("=" * 78)


def probe_all(url: str, config: dict[str, Any], timeout: int) -> tuple[list[ProbeResult], dict[str, Any]]:
    engines = build_engines(config)
    results_by_name: dict[str, ProbeResult] = {}

    with ThreadPoolExecutor(max_workers=min(5, len(engines))) as pool:
        futures = {pool.submit(engine.probe, url, timeout): engine for engine in engines}
        for future in as_completed(futures):
            engine = futures[future]
            try:
                results_by_name[engine.name] = future.result()
            except Exception as exc:
                results_by_name[engine.name] = ProbeResult(
                    engine.name, "ERROR", False, 0, f"Unexpected probe error: {exc}"
                )

    results = [results_by_name[e.name] for e in engines]
    return results, {e.name: e for e in engines}


def rank_result(result: ProbeResult) -> int:
    """Rank successful probes, applying media-type hints before generic priorities."""
    if not result.supported:
        return -1
    if result.engine == "streamlink" and result.metadata.get("is_live"):
        return 120
    if result.engine == "gallery-dl" and result.metadata.get("is_gallery"):
        return 115
    if result.engine == "aria2":
        return 70
    if result.engine == "cobalt":
        return 95
    if result.engine == "yt-dlp":
        return 100
    if result.engine == "streamlink":
        return 85
    if result.engine == "gallery-dl":
        return 80
    return result.confidence


def select_candidates(
    args: argparse.Namespace,
    results: list[ProbeResult],
    engines: dict[str, Any],
) -> list[tuple[Any, ProbeResult | None]]:
    if args.engine != "auto":
        engine = engines[args.engine]
        match = next((item for item in results if item.engine == args.engine), None)
        return [(engine, match)]

    candidates = [item for item in results if item.supported]
    candidates.sort(key=rank_result, reverse=True)
    if not candidates:
        return []

    if len(candidates) > 1 and not args.yes and sys.stdin.isatty():
        print("\nChoose an engine order:")
        print("  0. Automatic ranking (recommended)")
        for index, item in enumerate(candidates, start=1):
            print(f"  {index}. {item.engine}  |  {item.message}")
        try:
            choice = input("Selection [0]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = ""
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            selected = candidates.pop(int(choice) - 1)
            candidates.insert(0, selected)

    return [(engines[item.engine], item) for item in candidates]


def command_probe(args: argparse.Namespace, config: dict[str, Any]) -> int:
    try:
        url = validate_url(args.url)
    except ValueError as exc:
        print(f"Invalid URL: {exc}", file=sys.stderr)
        return 2

    results, _ = probe_all(url, config, args.timeout)
    if args.json:
        print(json.dumps([item.to_dict() for item in results], indent=2, ensure_ascii=False))
    else:
        print_results(results)
        count = sum(1 for item in results if item.supported)
        print(f"{count} engine(s) reported a usable extraction path.")
    return 0


def command_download(args: argparse.Namespace, config: dict[str, Any]) -> int:
    try:
        url = validate_url(args.url)
    except ValueError as exc:
        print(f"Invalid URL: {exc}", file=sys.stderr)
        return 2

    results, engines = probe_all(url, config, args.timeout)
    print_results(results)

    candidates = select_candidates(args, results, engines)
    if not candidates:
        print("\nNo installed engine reported support for this URL.")
        print("Try omnifetch doctor, install more engines, or force a specific engine.")
        return 1

    output_dir = resolve_output_dir(args, config)
    print(f"\nDownload destination: {output_dir}")
    failures: list[str] = []

    for index, (engine, probe_result) in enumerate(candidates):
        if index:
            print(f"\nFalling back to {engine.name}...")
        result = engine.download(url, output_dir, probe_result)
        if result.success:
            print(f"\nSuccess: {result.message}")
            if result.output_path:
                print(f"Saved to: {result.output_path}")
            print(f"Engine: {result.engine}")
            return 0
        failures.append(f"{engine.name}: {result.message}")
        print(f"\n{engine.name} failed: {result.message}")

    print("\nAll candidate engines failed:")
    for failure in failures:
        print(f"  - {failure}")
    return 1


def command_engines(config: dict[str, Any]) -> int:
    labels = {
        "yt-dlp": "General video/audio extraction",
        "cobalt": "Optional remote extraction through your configured Cobalt API",
        "streamlink": "Livestream and supported stream extraction",
        "gallery-dl": "Media galleries and image-hosting sites",
        "aria2": "Direct HTTP(S) file transfers",
    }
    for engine in build_engines(config):
        if engine.name == "cobalt":
            status = "configured" if engine.available() else "not configured"
        else:
            status = "installed" if engine.available() else "not installed"
        print(f"{engine.name:<12} {status:<16} {labels[engine.name]}")
    return 0


def command_doctor(config: dict[str, Any]) -> int:
    print(f"OmniFetch {__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {sys.platform}")
    print(f"Config: {config_path()}")
    print(f"Output: {config.get('output_dir') or default_output_dir()}")
    print()
    problems = 0
    for engine in build_engines(config):
        if engine.name == "cobalt":
            ok = engine.available()
            state = "configured" if ok else "disabled (optional)"
        else:
            ok = engine.available()
            state = "available" if ok else "missing"
        marker = _style("OK", "32;1") if ok else _style("INFO", "33")
        print(f"{marker:<12} {engine.name:<12} {state}")
        if engine.name in {"yt-dlp", "aria2"} and not ok:
            problems += 1

    ffmpeg = bool(shutil.which("ffmpeg"))
    print(f"{_style('OK' if ffmpeg else 'INFO', '32;1' if ffmpeg else '33'):<12} ffmpeg       " +
          ("available" if ffmpeg else "missing (recommended for merging/remuxing)"))
    if problems:
        print("\nInstall the missing core tools with the commands in README.md.")
        return 1
    return 0


def command_config(args: argparse.Namespace, config: dict[str, Any]) -> int:
    if args.config_action == "show":
        safe = dict(config)
        if "cobalt_auth" in safe:
            safe["cobalt_auth"] = "<not displayed>"
        print(json.dumps(safe, indent=2) if safe else "No custom settings.")
        print(f"Config file: {config_path()}")
        print("Cobalt credentials are read from OMNIFETCH_COBALT_AUTH, not saved in this file.")
        return 0

    if args.key == "output-dir":
        config["output_dir"] = str(Path(args.value).expanduser())
    elif args.key == "cobalt-api":
        value = args.value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            print("Cobalt API must start with http:// or https://.", file=sys.stderr)
            return 2
        config["cobalt_api"] = value
    save_config(config)
    print(f"Saved {args.key} to {config_path()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # A bare URL is shorthand for the download command.
    if arguments and arguments[0] not in COMMANDS:
        arguments.insert(0, "download")

    parser = make_parser()
    args = parser.parse_args(arguments)
    config = load_config()

    if args.command == "probe":
        return command_probe(args, config)
    if args.command == "download":
        return command_download(args, config)
    if args.command == "engines":
        return command_engines(config)
    if args.command == "doctor":
        return command_doctor(config)
    if args.command == "config":
        return command_config(args, config)
    parser.print_help()
    return 0

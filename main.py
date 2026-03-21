#!/usr/bin/env python3
"""
main.py — Auto-Clicker entry point.

Usage
-----
    python main.py                          # uses config.yaml
    python main.py -c my_event.yaml         # custom config
    python main.py --mode notify            # override mode
    python main.py --dry-run                # simulate without clicking
    python main.py --list-checks            # show what will be watched
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #

def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="auto-clicker",
        description="Monitor a URL and auto-register (or notify you) when a button appears.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  python main.py                            # default config.yaml, notify mode
  python main.py -c camp_registration.yaml  # custom config file
  python main.py --mode auto                # override to AUTO mode
  python main.py --dry-run --mode auto      # test form-fill without submitting
        """,
    )
    p.add_argument(
        "-c", "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to YAML config file (default: config.yaml)",
    )
    p.add_argument(
        "-m", "--mode",
        choices=["notify", "auto"],
        default=None,
        help="Override the mode set in config.yaml",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="(AUTO mode) simulate mouse/keyboard actions without actually clicking or submitting",
    )
    p.add_argument(
        "--list-checks",
        action="store_true",
        help="Print what the tool will watch for and exit",
    )
    return p


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
        print(
            "  Edit config.yaml with your target URL and details, or use -c <path>.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Deferred imports so argparse --help is instant
    from monitor import load_config, Monitor
    from logger_setup import setup_logger

    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"[ERROR] Bad config: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = setup_logger("auto_clicker", config.get("logging", {}))

    # ── --list-checks ──────────────────────────────────────────────────────
    if args.list_checks:
        el = config.get("element", {})
        mode = (args.mode or config.get("mode", "notify")).upper()
        print(f"\n  Config   : {config_path}")
        print(f"  URL      : {config['target_url']}")
        print(f"  Mode     : {mode}")
        print(f"  Interval : {config.get('check_interval', 5)}s")
        print(f"  Timeout  : {el.get('timeout', 0) or 'none'}s")
        print(f"  Selector : {el.get('selector', '(none)')}")
        print(f"  Text     : {el.get('text', '(none)')}")
        print(f"  Role     : {el.get('role', '(none)')} {el.get('role_name', '')}")
        if mode == "AUTO":
            fields = config.get("form_details", {}).get("fields", [])
            print(f"  Fields   : {len(fields)} configured")
        print()
        return

    # ── Normal run ─────────────────────────────────────────────────────────
    logger.info("Config loaded: %s", config_path.resolve())
    monitor = Monitor(
        config=config,
        mode_override=args.mode,
        dry_run=args.dry_run,
        logger=logger,
    )

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logger.info("Stopped by user (Ctrl+C).")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

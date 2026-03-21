"""
notifier.py — Cross-platform desktop notifications and sound alerts.

macOS  : osascript (notification) + afplay (sound)
Linux  : notify-send (notification) + paplay/aplay (sound)
Windows: PowerShell toast (notification) + winsound (sound)
Fallback: coloured terminal banner if OS integration fails.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("notifier")

# Built-in system sounds (per platform)
_SYSTEM_SOUNDS = {
    "darwin": [
        "/System/Library/Sounds/Glass.aiff",
        "/System/Library/Sounds/Ping.aiff",
        "/System/Library/Sounds/Tink.aiff",
    ],
    "linux": [
        "/usr/share/sounds/freedesktop/stereo/complete.oga",
        "/usr/share/sounds/alsa/Front_Center.wav",
        "/usr/share/sounds/ubuntu/stereo/message.ogg",
    ],
}


class Notifier:
    """Send desktop notifications and play sound alerts."""

    def __init__(self, config: dict) -> None:
        self.sound_enabled: bool = config.get("sound", True)
        self.sound_file: str = config.get("sound_file", "")
        self.repeat: int = max(1, int(config.get("repeat", 3)))
        self.repeat_interval: float = float(config.get("repeat_interval", 5))
        self._platform = sys.platform

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify(self, title: str, message: str) -> None:
        """Fire notification and sound in background threads (non-blocking)."""
        log.info("Sending desktop notification: %s", title)
        threading.Thread(
            target=self._send_notification, args=(title, message), daemon=True
        ).start()
        if self.sound_enabled:
            threading.Thread(target=self._sound_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    def _send_notification(self, title: str, message: str) -> None:
        dispatched = False
        try:
            if self._platform == "darwin":
                dispatched = self._notify_macos(title, message)
            elif self._platform.startswith("linux"):
                dispatched = self._notify_linux(title, message)
            elif self._platform == "win32":
                dispatched = self._notify_windows(title, message)
        except Exception as exc:
            log.debug("Notification dispatch error: %s", exc)

        if not dispatched:
            self._terminal_banner(title, message)

    def _notify_macos(self, title: str, message: str) -> bool:
        # Escape double-quotes for AppleScript
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        script = (
            f'display notification "{safe_msg}" with title "{safe_title}" '
            'sound name "Glass"'
        )
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=5
        )
        return result.returncode == 0

    def _notify_linux(self, title: str, message: str) -> bool:
        result = subprocess.run(
            ["notify-send", "--urgency=critical", "--expire-time=10000", title, message],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0

    def _notify_windows(self, title: str, message: str) -> bool:
        safe_title = title.replace("'", "\\'")
        safe_msg = message.replace("'", "\\'")
        ps = f"""
        Add-Type -AssemblyName System.Windows.Forms
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $notify.ShowBalloonTip(10000, '{safe_title}', '{safe_msg}',
            [System.Windows.Forms.ToolTipIcon]::Warning)
        Start-Sleep -Milliseconds 500
        $notify.Dispose()
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0

    @staticmethod
    def _terminal_banner(title: str, message: str) -> None:
        sep = "=" * 60
        print(f"\n\033[1;33m{sep}\033[0m")
        print(f"\033[1;31m  ALERT: {title}\033[0m")
        print(f"\033[0;37m  {message}\033[0m")
        print(f"\033[1;33m{sep}\033[0m\n", flush=True)

    # ------------------------------------------------------------------
    # Sound dispatch
    # ------------------------------------------------------------------

    def _sound_loop(self) -> None:
        for i in range(self.repeat):
            self._play_sound()
            if i < self.repeat - 1:
                time.sleep(self.repeat_interval)

    def _play_sound(self) -> None:
        try:
            custom = self.sound_file
            if custom and Path(custom).exists():
                self._play_file(custom)
                return

            if self._platform == "darwin":
                for path in _SYSTEM_SOUNDS["darwin"]:
                    if Path(path).exists():
                        subprocess.run(["afplay", path], capture_output=True, timeout=10)
                        return

            elif self._platform.startswith("linux"):
                for path in _SYSTEM_SOUNDS["linux"]:
                    if Path(path).exists():
                        for player in (["paplay"], ["aplay"], ["ogg123"]):
                            r = subprocess.run(
                                player + [path], capture_output=True, timeout=10
                            )
                            if r.returncode == 0:
                                return

            elif self._platform == "win32":
                import winsound  # type: ignore[import]
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

        except Exception as exc:
            log.debug("Sound playback failed: %s", exc)

    def _play_file(self, path: str) -> None:
        if self._platform == "darwin":
            subprocess.run(["afplay", path], capture_output=True, timeout=30)
        elif self._platform.startswith("linux"):
            for player in (["paplay"], ["aplay"], ["ogg123"]):
                r = subprocess.run(player + [path], capture_output=True, timeout=30)
                if r.returncode == 0:
                    return
        elif self._platform == "win32":
            import winsound  # type: ignore[import]
            winsound.PlaySound(path, winsound.SND_FILENAME)

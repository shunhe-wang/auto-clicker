"""
monitor.py — Core polling loop and element-detection engine.

Workflow
--------
1. Launch a headed Chromium browser (stealth-patched).
2. Navigate to target_url.
3. Every check_interval seconds, probe the page for the target element
   using one or more configured detection strategies (CSS selector,
   visible text, ARIA role+name).
4. On detection, hand off to either:
   - NOTIFY mode  → Notifier (desktop alert + sound, browser stays open)
   - AUTO mode    → FormFiller (automated click + form submission)
5. If a timeout is configured, exit gracefully when it is reached.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    async_playwright,
)

from form_filler import FormFiller
from logger_setup import setup_logger
from notifier import Notifier


# ---------------------------------------------------------------------------
# Stealth init script — removes the navigator.webdriver flag
# ---------------------------------------------------------------------------
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""


class Monitor:
    """Monitors a URL and acts when the target element becomes available."""

    def __init__(
        self,
        config: dict[str, Any],
        mode_override: str | None = None,
        dry_run: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.mode: str = (mode_override or config.get("mode", "notify")).lower()
        self.dry_run = dry_run
        self.log = logger or setup_logger("monitor", config.get("logging", {}))
        self.notifier = Notifier(config.get("notifications", {}))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self.log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self.log.info("Mode            : %s", self.mode.upper())
        self.log.info("Target URL      : %s", self.config["target_url"])
        self.log.info("Check interval  : %ss", self.config.get("check_interval", 5))
        el_cfg = self.config.get("element", {})
        self.log.info(
            "Watching for    : selector=%r  text=%r  role=%r",
            el_cfg.get("selector", ""),
            el_cfg.get("text", ""),
            el_cfg.get("role", ""),
        )
        if self.config.get("profile_dir"):
            self.log.info("Profile dir     : %s  (session will be saved)", self.config["profile_dir"])
        if self.dry_run:
            self.log.info("DRY RUN enabled — no real clicks or form submissions")
        self.log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        async with async_playwright() as pw:
            browser, context, page = await self._launch(pw)
            try:
                await self._navigate(page)
                await self._poll_loop(page)
            finally:
                # persistent context has no separate browser object
                if browser is not None:
                    await browser.close()
                else:
                    await context.close()

    # ------------------------------------------------------------------
    # Browser setup
    # ------------------------------------------------------------------

    async def _launch(self, pw) -> tuple[Browser | None, BrowserContext, Page]:
        """
        Launch Chromium.

        If ``profile_dir`` is set in config, a *persistent* context is used so
        that cookies, localStorage, and login sessions are saved across runs —
        useful when the target page requires being logged in.

        Returns ``(browser, context, page)`` where *browser* is ``None`` for
        persistent contexts (the context itself is the thing to close).
        """
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        ctx_kwargs = dict(
            viewport={"width": 1280, "height": 900},
            user_agent=ua,
            java_script_enabled=True,
            ignore_https_errors=True,
        )

        profile_dir: str = self.config.get("profile_dir", "")
        if profile_dir:
            # Persistent context: saves session state to disk
            context = await pw.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=launch_args,
                **ctx_kwargs,
            )
            await context.add_init_script(_STEALTH_JS)
            page = context.pages[0] if context.pages else await context.new_page()
            return None, context, page

        # Ephemeral context (default)
        browser = await pw.chromium.launch(headless=False, args=launch_args)
        context = await browser.new_context(**ctx_kwargs)
        await context.add_init_script(_STEALTH_JS)
        page = await context.new_page()
        return browser, context, page

    async def _navigate(self, page: Page) -> None:
        url = self.config["target_url"]
        self.log.info("Navigating → %s", url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2.0)
        except Exception as exc:
            self.log.error("Navigation failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self, page: Page) -> None:
        el_cfg: dict = self.config.get("element", {})
        interval: float = float(self.config.get("check_interval", 5))
        timeout: float = float(el_cfg.get("timeout", 0))  # 0 = no limit
        reload_on_check: bool = self.config.get("reload_on_check", False)

        start = time.monotonic()
        check_no = 0

        self.log.info("Monitoring started. Press Ctrl+C to stop.")

        while True:
            elapsed = time.monotonic() - start
            if timeout and elapsed > timeout:
                self.log.warning("Timeout reached (%.0fs). Stopping.", timeout)
                break

            check_no += 1
            self.log.debug("Check #%d  (elapsed %.0fs)", check_no, elapsed)

            try:
                element = await self._find_element(page, el_cfg)
            except Exception as exc:
                self.log.error("Error during element probe: %s", exc)
                # If the page crashed or navigated away, try re-opening it
                if any(k in str(exc).lower() for k in ("target", "closed", "crash")):
                    self.log.info("Attempting to re-navigate after error…")
                    try:
                        await self._navigate(page)
                    except Exception:
                        pass
                element = None

            if element is not None:
                self.log.info("✓ Target element detected! (check #%d)", check_no)
                if self.mode == "notify":
                    await self._handle_notify(page)
                else:
                    await self._handle_auto(page, element)
                break

            # Optional reload between checks
            if reload_on_check:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15_000)
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    self.log.debug("Reload failed: %s", exc)

            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # Element detection strategies
    # ------------------------------------------------------------------

    async def _find_element(self, page: Page, cfg: dict) -> Locator | None:
        """
        Try each configured detection strategy in order.
        Returns the first Locator that passes the probe, or None.

        The probe requires visible + enabled by default.  Set
        ``element.require_enabled: false`` in config to trigger on the first
        visible appearance even if the element is still disabled — useful in
        NOTIFY mode when you want the earliest possible alert.
        """
        require_enabled: bool = cfg.get("require_enabled", True)

        # 1. CSS selector
        if cfg.get("selector"):
            el = await self._probe(
                page.locator(cfg["selector"]).first,
                require_enabled=require_enabled,
            )
            if el:
                return el

        # 2. Visible text
        if cfg.get("text"):
            exact: bool = cfg.get("exact_text", False)
            candidate = page.get_by_text(cfg["text"], exact=exact).first
            el = await self._probe(
                candidate,
                require_clickable_tag=not cfg.get("any_tag", False),
                require_enabled=require_enabled,
            )
            if el:
                return el

        # 3. ARIA role + optional name
        if cfg.get("role"):
            kwargs: dict = {}
            if cfg.get("role_name"):
                kwargs["name"] = cfg["role_name"]
            candidate = page.get_by_role(cfg["role"], **kwargs).first
            el = await self._probe(candidate, require_enabled=require_enabled)
            if el:
                return el

        return None

    async def _probe(
        self,
        locator: Locator,
        require_clickable_tag: bool = False,
        require_enabled: bool = True,
    ) -> Locator | None:
        """
        Return *locator* if it passes all requested conditions; otherwise None.

        Parameters
        ----------
        require_clickable_tag:
            When True, reject elements whose HTML tag is not one of
            button / a / input / label / select.
        require_enabled:
            When True (default), the element must also pass ``is_enabled()``.
            Set False to match the instant the element becomes visible,
            even if it is still in a disabled state.
        """
        try:
            if not await locator.is_visible():
                return None
            if require_enabled and not await locator.is_enabled():
                return None
            if require_clickable_tag:
                tag: str = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag not in {"button", "a", "input", "label", "select"}:
                    return None
            return locator
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Mode handlers
    # ------------------------------------------------------------------

    async def _handle_notify(self, page: Page) -> None:
        """Send desktop alert and keep the browser open for the user."""
        self.notifier.notify(
            title="Auto-Clicker — Registration Open!",
            message=f"Target element is live.\n{page.url}",
        )
        self.log.info(
            "Notification sent. Browser window is open — click the button yourself."
        )
        self.log.info("Press Ctrl+C to exit when done.")
        while True:
            await asyncio.sleep(15)

    async def _handle_auto(self, page: Page, element: Locator) -> None:
        """Delegate to FormFiller for automated click + form submission."""
        filler = FormFiller(
            page=page,
            config=self.config,
            dry_run=self.dry_run,
            logger=self.log,
        )
        await filler.click_and_fill(element)


# ---------------------------------------------------------------------------
# Convenience loader (used by main.py)
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict) -> None:
    if not cfg.get("target_url"):
        raise ValueError("config.yaml must define 'target_url'")

    el = cfg.get("element", {})
    if not any(el.get(k) for k in ("selector", "text", "role")):
        raise ValueError(
            "config.yaml must define at least one of: "
            "element.selector, element.text, element.role"
        )

    mode = cfg.get("mode", "notify").lower()
    if mode not in ("notify", "auto"):
        raise ValueError(f"mode must be 'notify' or 'auto', got: {mode!r}")

    if mode == "auto":
        form = cfg.get("form_details", {})
        fields = form.get("fields", [])
        if not fields:
            raise ValueError(
                "mode is 'auto' but form_details.fields is empty — "
                "add at least one field mapping."
            )
        for i, field in enumerate(fields):
            has_selector = field.get("selector") or field.get("selectors")
            if not has_selector:
                raise ValueError(
                    f"form_details.fields[{i}] is missing 'selector' or 'selectors'"
                )
            if "value" not in field:
                raise ValueError(
                    f"form_details.fields[{i}] is missing 'value'"
                )

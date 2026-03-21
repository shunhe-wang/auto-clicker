"""
form_filler.py — AUTO mode: click the target element and fill the form.

Behaviour
---------
1. Move to the register/book button via a Bezier path and click it.
2. Wait for the form to appear: network-idle + first field visible.
3. Fill each configured field (fill() by default; human_type() if human_typing: true).
4. Locate the submit button (configured selector or auto-detection) and click it.
5. Verify success by waiting for a confirmation selector, text, or URL change.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from playwright.async_api import Locator, Page

from human_mouse import human_click, human_type


class FormFiller:
    """Orchestrates clicking and form-filling in AUTO mode."""

    # Submit button auto-detection candidates (tried in order)
    _SUBMIT_CANDIDATES = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit')",
        "button:has-text('Register')",
        "button:has-text('Sign Up')",
        "button:has-text('Sign up')",
        "button:has-text('Book')",
        "button:has-text('Book Now')",
        "button:has-text('Confirm')",
        "button:has-text('Complete')",
        "button:has-text('Continue')",
        "button:has-text('Proceed')",
        "[role='button']:has-text('Submit')",
    ]

    def __init__(
        self,
        page: Page,
        config: dict[str, Any],
        dry_run: bool = False,
        logger: logging.Logger | None = None,
    ) -> None:
        self.page = page
        self.config = config
        self.form = config.get("form_details", {})
        self.dry_run = dry_run
        self.human_typing: bool = bool(config.get("human_typing", False))
        self.log = logger or logging.getLogger("form_filler")
        self._mouse: tuple[float, float] | None = None   # tracked cursor pos

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def click_and_fill(self, trigger: Locator) -> None:
        """Click *trigger* (Register/Book button), fill the form, submit."""
        self.log.info("AUTO mode — clicking trigger element")
        original_url = self.page.url
        await self._click_locator(trigger, label="trigger button")

        # Wait for the form to actually be ready (network + DOM)
        await self._wait_for_form_ready()

        fields: list[dict] = self.form.get("fields", [])
        if not fields:
            self.log.warning("No fields configured under form_details.fields — nothing to fill.")
            return

        filled = 0
        for field_cfg in fields:
            ok = await self._fill_field(field_cfg)
            if ok:
                filled += 1
            await asyncio.sleep(random.uniform(0.25, 0.60))

        self.log.info("Filled %d / %d fields", filled, len(fields))

        if not self.dry_run:
            try:
                await self._submit()
            except RuntimeError as exc:
                self.log.error(str(exc))
                return
        else:
            self.log.info("[DRY RUN] Would click submit button")

        await self._check_success(original_url)

    # ------------------------------------------------------------------
    # Form readiness
    # ------------------------------------------------------------------

    async def _wait_for_form_ready(self) -> None:
        """
        Wait until the form is usable after clicking the trigger.
        Strategy: network quiet OR first configured field visible — whichever
        comes first. Falls back to a brief pause if neither resolves quickly.
        """
        # 1. Network idle (covers XHR-loaded modals and page transitions)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8_000)
        except Exception:
            pass

        # 2. Wait for first configured field to appear in the DOM.
        #    Respect the field's iframe setting so iframed forms are checked
        #    inside their frame rather than always against the top-level page.
        for field_cfg in self.form.get("fields", []):
            iframe_sel = field_cfg.get("iframe")
            frame = self.page.frame_locator(iframe_sel) if iframe_sel else self.page
            for sel in self._get_selectors(field_cfg):
                try:
                    await frame.locator(sel).first.wait_for(
                        state="visible", timeout=8_000
                    )
                    self.log.debug("Form ready — first field visible: %s", sel)
                    return
                except Exception:
                    continue

        # Fallback for forms we can't pre-detect
        await asyncio.sleep(random.uniform(0.8, 1.4))

    # ------------------------------------------------------------------
    # Field filling
    # ------------------------------------------------------------------

    async def _fill_field(self, field_cfg: dict) -> bool:
        selectors = self._get_selectors(field_cfg)
        raw_value = str(field_cfg.get("value", ""))
        field_type = field_cfg.get("type", "text")  # text | select | checkbox
        iframe_sel = field_cfg.get("iframe")        # optional iframe selector

        value = self._resolve(raw_value)
        if not selectors or not value:
            return False

        # Resolve the frame to search in (page or an iframe)
        frame = self.page
        if iframe_sel:
            try:
                frame = self.page.frame_locator(iframe_sel)
            except Exception as exc:
                self.log.warning("Could not enter iframe '%s': %s", iframe_sel, exc)

        for sel in selectors:
            try:
                el = frame.locator(sel).first

                # Wait for the field to be ready (visible + enabled)
                try:
                    await el.wait_for(state="visible", timeout=5_000)
                except Exception:
                    continue
                if not await el.is_enabled():
                    continue

                display_val = value if len(value) <= 30 else value[:27] + "..."
                self.log.info("Filling %-40s → %s", f"'{sel}'", display_val)

                await el.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.06, 0.14))

                # Click to focus
                await self._click_locator(el, label=f"field {sel}")
                await asyncio.sleep(random.uniform(0.08, 0.18))

                if field_type == "select":
                    if not self.dry_run:
                        await el.select_option(value)
                elif field_type == "checkbox":
                    if not self.dry_run:
                        want = value.lower() in ("true", "yes", "1", "on")
                        # is_checked() only works on real <input type="checkbox">.
                        # Faux checkboxes (div/span/role=checkbox) expose their
                        # state via aria-checked instead.
                        try:
                            already = await el.is_checked()
                        except Exception:
                            aria = await el.get_attribute("aria-checked")
                            already = str(aria).lower() in ("true", "1")
                        if already != want:
                            await el.click()
                else:
                    if not self.dry_run:
                        if self.human_typing:
                            # Character-by-character with Gaussian delays
                            await human_type(el, value, clear_first=True)
                        else:
                            # fill() is atomic and works correctly with React /
                            # masked / validated inputs; prefer it for reliability.
                            await el.fill(value)
                    else:
                        self.log.info("[DRY RUN] Would fill: %s", value)

                return True

            except Exception as exc:
                self.log.debug("Selector '%s' failed: %s", sel, exc)

        self.log.warning("Could not fill field — no selector matched: %s", selectors)
        return False

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _submit(self) -> None:
        """
        Find and click the submit button.
        Respects ``form_details.submit_iframe`` for forms whose submit button
        lives inside an iframe.
        Raises RuntimeError if no button can be found.
        """
        submit_iframe: str = self.form.get("submit_iframe", "")
        frame = self.page.frame_locator(submit_iframe) if submit_iframe else self.page

        # Try configured selector first
        configured: str = self.form.get("submit_selector", "")
        if configured:
            try:
                btn = frame.locator(configured).first
                await btn.wait_for(state="visible", timeout=5_000)
                if await btn.is_enabled():
                    self.log.info("Clicking configured submit button: %s", configured)
                    await self._click_locator(btn, label="submit button")
                    return
            except Exception as exc:
                self.log.debug("Configured submit selector failed: %s", exc)

        # Auto-detect (only within the specified frame)
        for sel in self._SUBMIT_CANDIDATES:
            try:
                btn = frame.locator(sel).first
                if await btn.is_visible() and await btn.is_enabled():
                    self.log.info("Auto-detected submit button: %s", sel)
                    await self._click_locator(btn, label="submit button")
                    return
            except Exception:
                continue

        raise RuntimeError(
            "Could not find a submit button. "
            "Set form_details.submit_selector in config.yaml."
        )

    # ------------------------------------------------------------------
    # Success verification
    # ------------------------------------------------------------------

    async def _check_success(self, original_url: str) -> bool:
        """
        Verify registration success.  Tries (in order):
        1. Configured success_selector appears (inside success_iframe if set)
        2. Configured success_text appears    (inside success_iframe if set)
        3. Page URL changes from original_url (page-level only)
        """
        success_sel: str = self.form.get("success_selector", "")
        success_txt: str = self.form.get("success_text", "")
        success_iframe: str = self.form.get("success_iframe", "")

        # Resolve which frame to search; fall back to full page if not set.
        frame = self.page.frame_locator(success_iframe) if success_iframe else self.page

        if success_sel:
            try:
                await frame.locator(success_sel).wait_for(timeout=15_000)
                self.log.info("SUCCESS — confirmation element found: %s", success_sel)
                return True
            except Exception:
                pass

        if success_txt:
            try:
                await frame.get_by_text(success_txt, exact=False).wait_for(timeout=15_000)
                self.log.info("SUCCESS — confirmation text found: '%s'", success_txt)
                return True
            except Exception:
                pass

        # URL navigation is a reliable weak signal (always page-level)
        try:
            await self.page.wait_for_url(
                lambda url: url != original_url, timeout=15_000
            )
            self.log.info("Page navigated to %s — likely success", self.page.url)
            return True
        except Exception:
            pass

        self.log.warning(
            "Could not confirm successful registration. "
            "Check the browser window manually."
        )
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_selectors(self, field_cfg: dict) -> list[str]:
        """
        Return the list of CSS selectors to try for a field.

        Supports two formats in config.yaml:
          selectors: ["sel1", "sel2"]   ← preferred (no ambiguity)
          selector: "sel1"              ← single selector (no comma-splitting)
        """
        if "selectors" in field_cfg:
            raw = field_cfg["selectors"]
            if isinstance(raw, list):
                return [str(s).strip() for s in raw if str(s).strip()]
            return [str(raw).strip()]
        sel = str(field_cfg.get("selector", "")).strip()
        return [sel] if sel else []

    def _resolve(self, template: str) -> str:
        """
        Replace ``{key}`` placeholders with values from form_details.

        Uses a single ``re.sub`` pass so substituted values are never
        re-scanned — a value that happens to contain ``{something}`` will
        not trigger a second round of substitution.
        Unknown placeholders (no matching key) are left as-is.
        """
        import re
        vars_: dict[str, str] = {
            k: v for k, v in self.form.items() if isinstance(v, str)
        }
        return re.sub(
            r"\{(\w+)\}",
            lambda m: vars_.get(m.group(1), m.group(0)),
            template,
        )

    async def _click_locator(self, locator: Locator, label: str = "element") -> None:
        """
        Click *locator* with human-like mouse movement when possible.

        Falls back to ``locator.click()`` in three situations:
        - The element has no bounding box (hidden, not yet rendered).
        - The element is inside an iframe, where page-level mouse coordinates
          can be unreliable due to scroll offset or coordinate-space differences.
        - The human_click() call raises for any reason.

        ``locator.click()`` is always safer for framed or unusual elements;
        the Bezier path is a best-effort nicety on top.
        """
        if self.dry_run:
            self.log.info("[DRY RUN] Would click %s", label)
            return

        box = await locator.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2 + random.uniform(-3.0, 3.0)
            cy = box["y"] + box["height"] / 2 + random.uniform(-3.0, 3.0)
            self.log.debug("Human-click %s at (%.0f, %.0f)", label, cx, cy)
            try:
                self._mouse = await human_click(self.page, cx, cy, self._mouse)
                return
            except Exception as exc:
                self.log.debug(
                    "human_click failed for %s (%s) — falling back to locator.click()",
                    label, exc,
                )
        else:
            self.log.debug("No bounding box for %s — using locator.click()", label)

        # Reliable fallback: let Playwright route the click through the locator's
        # own frame context, which handles iframes and coordinate edge-cases.
        await locator.click()

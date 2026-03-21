# Auto-Clicker

A Python + Playwright tool that monitors a target URL and either **notifies you** the instant a registration/booking element appears, or **automatically fills the form and submits** on your behalf.

---

## Features

| Feature | Details |
|---|---|
| **NOTIFY mode** | Desktop notification + repeating sound alert the moment the element goes live — you click yourself |
| **AUTO mode** | Automated click, Bezier mouse movement, atomic `fill()` by default (reliable on React/masked inputs), or opt-in character-by-character typing with `human_typing: true` |
| **Multi-strategy detection** | CSS selector, visible text match, or ARIA role + name — use any combination |
| **Stealth browser** | Headed Chromium with `navigator.webdriver` removed and a realistic user-agent |
| **Configurable** | One YAML file per event; field mappings use `{template}` variables |
| **Full logging** | Timestamped console output (coloured when `colorlog` is installed) + persistent log file |
| **Dry-run mode** | Simulate AUTO mode without sending a single real click or keystroke |
| **Cross-platform** | macOS, Linux, Windows |

---

## Requirements

- Python 3.10 +
- `pip install -r requirements.txt`
- `playwright install chromium`

---

## Quick Start

```bash
# 1. Clone / download the project
cd auto-clicker

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Playwright's Chromium browser
playwright install chromium

# 4. Edit the config
cp config.yaml my_event.yaml   # config.yaml is the annotated template
# (edit my_event.yaml — see Configuration below)

# 5. Run
python main.py -c my_event.yaml
```

---

## Configuration

Every option lives in a single YAML file. The annotated `config.yaml` is the reference.

### Minimal NOTIFY example

```yaml
target_url: "https://eventbrite.com/e/my-event"

element:
  selector: "button.js-buy-button"
  timeout: 7200          # give up after 2 hours

check_interval: 10
mode: "notify"

notifications:
  sound: true
  repeat: 5
  repeat_interval: 8
```

### Minimal AUTO example

```yaml
target_url: "https://campregistration.example.com"

element:
  text: "Register Now"   # matches any visible element containing this text
  timeout: 3600

check_interval: 5
mode: "auto"

form_details:
  first_name: "Jane"
  last_name:  "Doe"
  email:      "jane@example.com"
  phone:      "+1 555-123-4567"

  fields:
    - selector: "input[name='firstName']"
      value: "{first_name}"
    - selector: "input[name='lastName']"
      value: "{last_name}"
    - selector: "input[type='email']"
      value: "{email}"
    - selector: "input[type='tel']"
      value: "{phone}"

  submit_selector:  "button[type='submit']"
  success_selector: ".registration-confirmed"
```

### Full config reference

```yaml
target_url: "https://example.com"

element:
  # --- detection (use one or more) ---
  selector:        "button.register"   # CSS selector
  text:            "Register Now"      # visible text (partial match)
  exact_text:      false               # require exact text match
  any_tag:         false               # match text in non-interactive tags too
  role:            "button"            # ARIA role
  role_name:       "Register"          # ARIA accessible name (with role)
  require_enabled: true                # false = trigger on visible-only (see Tips)
  timeout:         3600                # seconds before giving up (0 = forever)

check_interval: 5                 # seconds between probes
reload_on_check: false            # reload full page between checks

mode: "notify"                    # "notify" | "auto"

form_details:
  # template variables
  first_name: "Jane"
  last_name:  "Doe"
  full_name:  "Jane Doe"
  email:      "jane@example.com"
  phone:      "+1 555-123-4567"

  fields:
    - selector: "input[name='firstName']"
      value:    "{first_name}"
    - selector: "input[name='lastName']"
      value:    "{last_name}"
    - selector: "select[name='tshirt_size']"
      value:    "M"
      type:     "select"          # "text" (default) | "select" | "checkbox"
    - selector: "input[name='agree']"
      value:    "true"
      type:     "checkbox"

  submit_selector:  "button[type='submit']"   # omit to auto-detect
  success_selector: ".confirmation-box"       # wait for this after submit
  success_text:     "you're registered"       # or check for this text

notifications:
  sound:           true
  sound_file:      ""             # path to custom .wav/.aiff/.ogg (optional)
  repeat:          3              # how many times to sound the alert
  repeat_interval: 5              # seconds between repeats

logging:
  file:  "auto_clicker.log"
  level: "INFO"                   # DEBUG | INFO | WARNING | ERROR
```

---

## CLI Options

```
python main.py [OPTIONS]

  -c, --config FILE    YAML config to use (default: config.yaml)
  -m, --mode MODE      Override mode: notify | auto
  --dry-run            Simulate AUTO mode — no real clicks or submits
  --list-checks        Print what will be watched and exit
```

### Examples

```bash
# Watch with notify mode (override config)
python main.py -c ticket.yaml --mode notify

# Test your field mappings without real submission
python main.py -c signup.yaml --mode auto --dry-run

# See what the tool will watch for
python main.py -c signup.yaml --list-checks
```

---

## How AUTO Mode Works

1. **Element detected** — the polling loop finds the configured button/link.
2. **Human mouse move** — the cursor follows a randomised cubic Bezier path with micro-jitter and optional overshoot.
3. **Click** — button held for a realistic random duration.
4. **Form fill** — each field is focused (Bezier click), then filled via Playwright's `fill()` by default (atomic, works with React/masked inputs). Set `human_typing: true` in config to switch to character-by-character Gaussian-delayed typing instead.
5. **Submit** — configured or auto-detected submit button clicked; raises an error if not found so the run doesn't silently continue.
6. **Verify** — waits for a success selector, success text, or URL change.

---

## Tips

**Finding the right CSS selector**

Open DevTools (F12 → Elements), right-click the target button → *Copy → Copy selector*. Paste it under `element.selector`.

**Finding field selectors**

Right-click a form input → *Inspect*. Use the `name`, `id`, or `placeholder` attributes to build a reliable selector (e.g. `input[name='email']`).

**The element only appears after login**

Log in manually in the browser window that opens, then the tool continues monitoring. Do not close the window. Set `profile_dir` to avoid logging in again next run.

**Form fields are inside an iframe**

Find the iframe's CSS selector (e.g. `iframe.booking-widget`) and add `iframe: "iframe.booking-widget"` to each affected field config. If the submit button is also inside the iframe, add `submit_iframe: "iframe.booking-widget"` under `form_details`.

**Form fields are inside shadow DOM**

Playwright's CSS engine can pierce open shadow roots using the `>>` combinator (e.g. `my-component >> input[name='email']`). Put that as the `selector` value for the field. This works for most standard web components. Closed shadow roots and deeply nested custom elements may still be unreachable with any selector strategy.

**The site uses a JavaScript framework and the element appears without a reload**

Keep `reload_on_check: false`. The tool probes the live DOM each cycle.

**The registration page only goes live at a known time**

Use a short `check_interval` (2–5 s) and set `timeout` to a few hours.

**The button briefly appears disabled before it becomes clickable**

Some sites render the button visible (greyed-out) a moment before enabling it. In NOTIFY mode, you can catch the earliest appearance by setting `element.require_enabled: false` — you'll be alerted as soon as it's visible, even if it's still disabled, giving you a head start. Leave it `true` for AUTO mode; clicking a disabled button does nothing.

**Multiple events**

Keep a separate YAML file per event. Run multiple instances in different terminals with `-c`.

---

## Files

```
auto-clicker/
├── main.py          — CLI entry point
├── monitor.py       — Polling loop + element detection
├── form_filler.py   — AUTO mode: click + fill + submit
├── human_mouse.py   — Bezier mouse paths + human-like typing
├── notifier.py      — Desktop notifications + sound (cross-platform)
├── logger_setup.py  — Shared logging factory
├── config.yaml      — Example / template configuration
├── requirements.txt
└── README.md
```

---

## Limitations

- **CAPTCHAs** — the tool will not bypass CAPTCHA challenges; it stops and leaves the window open.
- **2FA / password gates** — log in manually in the opened browser; the tool resumes automatically. Use `profile_dir` to persist the session across restarts.
- **Iframes** — fields and submit buttons inside iframes are supported via the `iframe` / `submit_iframe` field options. The readiness check also respects iframes. Shadow DOM is not supported; Playwright's standard selectors do not pierce it.
- **Bot detection** — the tool launches a real headed browser and patches a few common fingerprint signals (`navigator.webdriver`, `plugins`, `languages`). This is a light touch — it is not comprehensive anti-bot evasion. Determined bot-detection systems can still identify it. If a site blocks you, there is no configuration knob that will reliably fix that.
- **Faux interactive elements** — custom checkbox/radio widgets that use `div` or `span` with ARIA roles are handled via `aria-checked` fallback, but heavily customised widgets may still behave unexpectedly.

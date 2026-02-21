# Jirai Kei GUI Brainstorm (SOMI)

## What I reviewed first

- `somicontroller.py` defines the main dashboard shell and applies global theme tokens through `app_stylesheet()` from `gui/themes/default_dark.py`.
- `gui/aicoregui.py` is the best candidate for unique visual identity because it has both chat and study (RAG) flows plus custom inline widget styles.
- `persona.py` currently uses default widgets with almost no style system integration; it is ideal for a dedicated themed pass.
- `gui/speechgui.py`, `gui/twittergui.py`, `gui/telegramgui.py`, and `gui/dataagentgui.py` mostly use `dialog_stylesheet()` with pockets of hard-coded accent styles.

## Current visual system (quick diagnosis)

1. **Single dark-token palette**
   - The current theme is neutral gray with cyan/green accents.
   - It is functionally clean, but not stylistically distinct.

2. **Mixed styling approach**
   - Some screens rely on global helpers (`dialog_stylesheet`).
   - Others include one-off inline style strings (especially in `aicoregui.py` and `speechgui.py`).
   - This makes global visual shifts harder than necessary.

3. **Strong modular architecture for theming retrofit**
   - Most dialogs are isolated entry points and can adopt a new token map with low risk.
   - The existing card pattern (`QFrame#card`) in `somicontroller.py` is already a good base for “fashion-like” skinning.

## Jirai Kei direction (adapted for SOMI)

Jirai Kei aesthetic translated for software (not cosplay mimicry):

- **Palette:** smoky charcoal + muted mauve + dusty rose + soft lavender + pearl text.
- **Surface language:** layered cards, satin-like highlights, soft inner borders.
- **Typography mood:** elegant/high-contrast headings with practical body font fallback.
- **Motion:** subtle fades and pulse glows, never high-energy cyberpunk flicker.
- **Iconography:** ribbons, hearts, bows, cameo frames used minimally as accents.

## Proposed token set (new theme module)

Create `gui/themes/jirai_kei.py` with semantic tokens such as:

- `bg_main`: `#141018`
- `bg_card`: `#1c1622`
- `bg_surface`: `#241b2d`
- `text_main`: `#f1e8f5`
- `text_muted`: `#c7b6cc`
- `accent_primary`: `#d79bb7` (dusty rose)
- `accent_secondary`: `#b8a2d9` (lavender)
- `accent_alert`: `#ff8fb1`
- `border_soft`: `#3a2f46`
- `border_focus`: `#9a7bb7`

And expose:

- `app_stylesheet()`
- `dialog_stylesheet()`
- optional helpers: `chip_style(kind)`, `status_color(level)`

## Unique concept for `aicoregui` (signature idea)

### “Velvet Mode” for AI Core

AICore becomes the only module with a distinctive *interactive identity* while staying consistent with the global theme.

Features:

1. **Persona Aura Ring**
   - Around selected agent name, render a soft glow color derived from persona key hash.
   - Gives each persona a recognizable “mood color” without manual config.

2. **Typing Presence Ribbon**
   - Replace plain dot cycling with a tiny animated ribbon line under the response area.
   - States: `Thinking`, `Composing`, `Refining`.

3. **Memory Lace Markers**
   - In chat output, prepend small visual tags for response provenance:
     - `♥ Memory`
     - `✦ RAG`
     - `☁ Live`
   - Enables trust transparency while preserving aesthetic voice.

4. **Study Atelier Panel**
   - Reframe RAG ingestion as “Atelier” with elegant status cards:
     - Indexed sources
     - Last ingestion time
     - Source quality/confidence score

5. **Dual-tone bubbles (assistant-only)**
   - User text stays neutral.
   - Assistant text gets a muted rose-lavender gradient bubble.

## Rollout plan (safe order)

1. **Phase 1 — Theme infrastructure**
   - Add `jirai_kei.py` theme file.
   - Add a simple theme selector in `somicontroller.py` settings path.

2. **Phase 2 — Main dashboard parity**
   - Port `somicontroller.py` cards, tabs, chips, waveform colors.

3. **Phase 3 — Dialog unification**
   - Migrate `twittergui.py`, `telegramgui.py`, `speechgui.py`, and `dataagentgui.py` off one-off inline colors.

4. **Phase 4 — AICore signature**
   - Implement Velvet Mode features only in `aicoregui.py`.

5. **Phase 5 — Persona editor polish**
   - Apply theme and add compact “preview card” for each persona.

## Concrete UI copy examples

- `AI Chat` → `Velvet Chatroom`
- `Study Material (RAG)` → `Atelier Archive`
- `Ingest Websites` → `Collect Web Clippings`
- `Clear Studies` → `Clear Atelier Index`

## Risk notes

- PyQt text rendering and gradients differ slightly by platform; keep fallback solid colors.
- Inline hard-coded styles should be reduced first to avoid visual drift.
- Avoid oversaturating pink; accessibility contrast must remain high for long sessions.

## Success criteria

- Theme can be toggled without breaking workflows.
- All existing dialogs retain functionality.
- `aicoregui` feels unmistakably special but still “belongs” to SOMI.

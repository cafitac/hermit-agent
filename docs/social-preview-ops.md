# GitHub social preview operations

This document explains how to keep Hermit's GitHub social preview image aligned with the current repository positioning.

## Canonical assets

- Editable source: `docs/assets/hermit-social-preview.svg`
- Upload-ready export: `docs/assets/hermit-social-preview.png`
- Local review page: `docs/assets/hermit-social-preview-review.html`

Treat `hermit-social-preview.svg` as the source of truth. Regenerate the PNG from it whenever the card copy or layout changes.

## Current message hierarchy

The image should communicate this, in order:

1. Claude Code or Codex does the planning.
2. Hermit does the repetitive repo execution.
3. The executor lane defaults toward predictable local or flat-rate routing.

If a future edit weakens that planner/executor split, update the asset before changing the GitHub preview image.

## When to refresh the social preview

Refresh the image when any of these change:

- README hero copy or top-level positioning
- Repository description or tagline
- Core audience definition
- Product framing around Claude Code / Codex / MCP executor lane
- Visual branding such as headline, color palette, or comparison emphasis

## Local review workflow

### 1. Review the SVG copy

Open these files together:

- `docs/assets/hermit-social-preview.svg`
- `docs/open-source-positioning.md`
- `README.md`

Check that the headline and supporting labels still match the live repository story.

### 2. Review the browser page locally

Open:

- `docs/assets/hermit-social-preview-review.html`

This page is for quick visual review before exporting or uploading.

### 3. Regenerate the PNG export

From the repository root:

```bash
magick docs/assets/hermit-social-preview.svg docs/assets/hermit-social-preview.png
```

Expected result:
- `docs/assets/hermit-social-preview.png` exists
- dimensions remain `1280x640`

### 4. Verify the output shape

```bash
file docs/assets/hermit-social-preview.png
```

Expected output should include:
- `PNG image data`
- `1280 x 640`

## GitHub upload steps

1. Open the repository on GitHub.
2. Go to `Settings`.
3. In the repository settings page, open the social preview section near the branding/Open Graph controls.
4. Upload `docs/assets/hermit-social-preview.png`.
5. Save the change.
6. Hard-refresh the repository homepage and any external preview surfaces if the old card is cached.

If the GitHub UI wording shifts, search within Settings for `Social preview` or `Open Graph image`.

## Upload checklist

Before uploading, confirm all of the following:

- The card headline still says the planner/executor split clearly.
- Hermit is positioned as the executor layer, not another premium planner.
- Claude Code / Codex naming matches the current README.
- No provider-specific pricing claim has crept into the image.
- The PNG was regenerated from the latest SVG.
- The README `See also` section still points at the same asset paths.

## Post-upload checklist

After uploading on GitHub, verify:

- The repo homepage preview shows the new image.
- The preview still reads well when scaled down.
- The card is legible against GitHub's dark and light surrounding chrome.
- The visual message matches the README opening section.

## Maintenance notes

- Keep the PNG checked into the repository so maintainers can upload a known-good artifact without regenerating it.
- Keep the SVG editable and human-readable so copy tweaks remain cheap.
- If the image concept changes substantially, update `docs/open-source-positioning.md` at the same time so future refreshes do not drift.

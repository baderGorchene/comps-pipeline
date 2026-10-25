# photos

## Purpose
Obtain listing photos for SHORTLISTED comps only.

## Status
PLACEHOLDER, Phase 2. No scraping or browser automation code until the source is decided in writing.

## Waiting on
1. Choice of photo source.
2. Sam's confirmation that his MLS subscriber agreement permits the chosen method.

MLS photos are copyrighted and many MLSs restrict automated access; an account suspension would directly harm Sam's business.

Source options, in order of preference:

1. Official MLS photo download or data feed available to appraisers.
2. Photos already available through Aivre.
3. Semi-automatic: Sam opens each listing himself; the tool saves images from the open page at human pace.
4. Automated browser session, ONLY if explicitly permitted: dedicated Chrome profile used only for MLS (Chrome 136+ ignores remote debugging on the default profile), debugging port bound to localhost, rate limited, browser closed after the run. Never use Sam's personal profile. Never log cookies.

## Planned design
- `PhotoSource` protocol with one implementation per option.
- Layout `data/photos/<mls_number>/`.
- Pillow resize to a configured max size.
- Manifest with SHA-256 per image.
- Skip already-downloaded images.

## Interface
`PhotoSource.fetch(mls_numbers: list[str]) -> dict[str, list[Path]]`

# Price Monitor — Project Rules

## Architecture Doc is the Source of Truth

**MANDATORY:** Before making any changes to this project:
1. Read `ARCHITECTURE.md` to understand the current design
2. Follow the patterns and decisions documented there
3. After ANY structural change (new file, new feature, new decision), update `ARCHITECTURE.md` immediately

**Never** add a new file, module, or feature without documenting it in `ARCHITECTURE.md` first or immediately after.

## Project Location
`C:\Users\Admin\.claude\projects\price-monitor`

## Stack
Python 3.12 / Vercel (serverless Python + static) / Tailwind CSS (CDN) / Chart.js / GitHub Actions
Data: docs/db.json (JSON file, version-controlled)
See ARCHITECTURE.md for full details.

## Self-Testing After Deploy

**MANDATORY — follow this exact sequence after EVERY deploy:**
1. **API test** — curl all changed endpoints, verify JSON responses
2. **Desktop test** — open site in Chrome, click through all changed flows
3. **MOBILE TEST** — resize to 375px or use Chrome mobile emulation, check ALL changed pages
4. Only notify the user when ALL 3 pass, OR fix bugs yourself first
5. Never hand off an untested deploy to the user

**⚠️ MOBILE CHECK IS NOT OPTIONAL.** If you skip step 3, the deploy is not complete. This has been a recurring failure — IC must verify mobile layout is checked before marking any deploy task as done.

## Feature Testing Rule

**MANDATORY:** Every feature must be tested with **at least 2 different scenarios** before marking it done:
- Scenario 1: Happy path (normal expected use)
- Scenario 2: Different input/product/edge case
- Both scenarios must be tested via the actual UI (click buttons, not just curl)
- Use `window.confirm = () => true` in Chrome JS to bypass confirm dialogs during automated testing

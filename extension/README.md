# Comps Shortlist — Browser Sidebar Extension (Chrome & Edge)

Run the Comps Shortlist platform directly inside Chrome or Edge's native **Side Panel** next to your appraisal software, MLS portal, or HCAD tab.

## Install (30 seconds)

1. Start the Comps Shortlist server locally (`run.bat` or `uv run python manage.py runserver`) — or have your deployed URL ready (e.g. Hugging Face Space URL).
2. Open your browser's Extensions page:
   - **Chrome:** `chrome://extensions`
   - **Edge:** `edge://extensions`
3. Turn on **Developer mode** (top right in Chrome, left sidebar in Edge).
4. Click **Load unpacked** and select this `extension/` folder.
5. Pin **Comps Shortlist — UAD 3.6 Sidebar** to your toolbar and click its icon to open the sidebar.

## Switching Between Local and Deployed URL

Click the **⚙** button in the sidebar header to set any server URL (defaults to `http://127.0.0.1:8000`). Your setting is saved automatically.

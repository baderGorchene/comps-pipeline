// Open the side panel directly when the user clicks the extension toolbar icon.
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((err) => console.error("sidePanel.setPanelBehavior failed:", err));

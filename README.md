# DataNodes Downloader

**DataNodes Downloader** is a utility for bulk downloading files from the DataNodes site using POST requests to obtain download links. The program accepts links from the user, processes them sequentially, and saves the redirect URLs to a text file named `results.txt`.

## Usage Guide

### Requirements

- **Node.js** installed on your system.
- **Axios** for making HTTP requests. Install it with the following command:

  ```
  npm init -y
  ```
      npm install axios

1. Run the script:
```
node datanodes_downloader.js
```

2. Enter the links:
   * Paste the links one per line and press Enter.
   * To finish input and start processing, enter an empty line and press Enter.

3. Results:
   * After processing all the links, the results will be saved in the results.txt file.

---

## Python GUI Edition (new)

This repository now also includes a full Python desktop app with a styled interface:

- File: `dn_gui_downloader.py`
- Dependencies file: `requirements-python.txt`

### Features

- Modern GUI (input panel, logs, results table, direct links tab)
- Bulk processing of DataNodes links
- Retry logic + configurable timeout
- Multi-worker processing
- Import links from `.txt`
- Copy/export direct links
- Auto-save GUI settings (`downloader_gui_config.json`)

### Run (Python)

1. Install dependencies:

   ```bash
   pip install -r requirements-python.txt
   ```

2. Launch app:

   ```bash
   python dn_gui_downloader.py
   ```

3. Paste one DataNodes link per line, click **Start**, then export/copy results.

---

## NovaNode HyperDL (Premium GUI)

New advanced Python app focused on real file downloading with queue control:

- App file: `novanode_hyperdl.py`
- Session file: `novanode_session.json`
- App settings file: `novanode_settings.json`
- Branding logo: `branding/novanode_logo.svg`

### Key features

- Ultra-clean SaaS-style interface
- Auto provider detection by URL
- Supported providers: DataNodes, PixelDrain, MediaFire, GoFile (token), and direct/redirect links
- Per-link progress bar (one bar per queued link)
- Sequential download flow (one by one)
- Output folder picker
- Pause and resume safely
- Continue later after app restart with session restore
- Resume partial files from `.part` files
- Strong retry/error handling for both resolve and download phases

### GoFile note

GoFile integration uses the official API and requires your API token in app settings (`GoFile API token` field).

### Run NovaNode HyperDL

1. Install Python dependency:

   ```bash
   pip install -r requirements-python.txt
   ```

2. Start the app:

   ```bash
   python novanode_hyperdl.py
   ```

3. Workflow:
   - Paste links in the left panel
   - Click **Add to Queue**
   - Choose output folder
   - Click **Start Queue**
   - (Optional) Fill GoFile token before queue start if using `gofile.io` links
   - Use **Pause / Resume / Save Session / Restore Session** as needed

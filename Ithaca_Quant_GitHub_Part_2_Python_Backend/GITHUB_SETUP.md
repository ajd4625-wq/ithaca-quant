# Ithaca Quant v0.6 — GitHub upload

This distribution is split into two ZIP archives. **GitHub does not extract ZIP files automatically.**

1. Extract **both** archives into the **same directory**, preserving folder names.
2. You should have `extension/`, `backend/`, `tests/`, `scripts/`, `docs/`, `README.md`, `.gitignore`, and `start_mac.command`.
3. Create a new GitHub repository. Choose **Add file → Upload files** and drag in the extracted files and folders (not the ZIP archives), then commit.
   If your browser doesn't accept folders, run `git init`, `git add .`, `git commit -m "Initial Ithaca Quant v0.6"`, connect the remote, and push.
4. Start the backend locally: `python3 -m pip install -r backend/requirements.txt` and `python3 backend/server.py`.
5. In Chrome, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select the `extension/` directory.

A Chrome extension cannot run as only two source files: Chrome requires a `manifest.json`, JavaScript, and bundled HTML/CSS/assets. These ZIPs are two convenient transfer packages, not two source files.

**Security:** Keep provider API keys in environment variables; don't commit `.env` files, locally recorded predictions (`*.sqlite3`), or authentication tokens. This is source distribution, not a production-hosted backend.

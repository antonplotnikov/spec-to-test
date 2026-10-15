# Deployment guide

## 1. Publish the code on GitHub

Run these from the `spec-to-test` folder (use your own GitHub username if you fork the project).

```bash
git init -b main
git add .
git status                       # check: no .env, .venv, .spec_to_test_data, secrets.toml
git commit -m "Release v1.1.0"
```

Create an **empty public repository** named `spec-to-test` on GitHub (no
README, no license — they already exist), then:

```bash
git remote add origin https://github.com/antonplotnikov/spec-to-test.git
git push -u origin main
```

Wait for the **CI** workflow to pass (Actions tab), then tag the release:

```bash
git tag -a v1.1.0 -m "Spec-to-Test v1.1.0"
git push origin v1.1.0
```

Create the GitHub release (web UI: Releases → Draft a new release → tag
`v1.1.0`, paste the 1.1.0 section of `CHANGELOG.md`), or with the GitHub CLI:

```bash
gh release create v1.1.0 --title "Spec-to-Test v1.1.0" --notes-file docs/release-notes-v1.1.0.md
```


## 2. Deploy on Streamlit Community Cloud

1. Sign in at https://share.streamlit.io with GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Repository: `antonplotnikov/spec-to-test`, branch `main`,
   main file path `app.py`.
4. **Advanced settings**:
   - Python version: **3.11** (tested) or 3.12 (tested in CI only).
   - Secrets: paste
     ```toml
     SPEC_TO_TEST_STORAGE = "session"
     ```
     `session` is the default everywhere (there is no Cloud detection any
     more); setting it explicitly documents the intent. Never set `local`
     on a public or shared deployment: every visitor would read and write the
     same folder on the server.
5. Click **Deploy**. Streamlit installs `requirements.txt` only (no dev or AI
   packages) and reads `.streamlit/config.toml` (2 MB upload limit, theme).

### What to check after deployment

- The app opens in English; switching to Українська / Русский works.
- Analyze `examples/password_reset.md` (paste its text): 9 requirements.
- The sidebar says "Your work is kept only for this browser session".
- Open the app in a private window: nothing from the first session appears.
- Upload a TXT and a PDF file; try a 3 MB file (expect a size error).
- Download each export.

### AI on a public deployment (optional, not recommended by default)

Every visitor's AI run would use **your** API key and budget. If you still
want it:

1. Add the SDK you need to `requirements.txt` (Streamlit Cloud installs only
   that file): `anthropic>=1.0,<2` for Claude or `openai>=2.0,<4` for OpenAI.
2. Add to the app's Secrets:
   ```toml
   AI_PROVIDER = "anthropic"          # or "openai" with OPENAI_API_KEY
   ANTHROPIC_API_KEY = "<your key>"
   AI_LOCK_SETTINGS = "true"          # visitors cannot switch provider or model
   ```
3. Set a spending limit for the key in the provider's console.

Ollama and self-hosted OpenAI-compatible servers are not an option on Streamlit
Cloud unless they are reachable over https (they need a server you run). Each
visitor can still turn AI off for their own session in **AI settings**.

Never commit the key. Streamlit secrets are not part of the repository.

## 3. Run locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py
```

By default nothing is saved: work lives only in the browser session. To save
work to `.spec_to_test_data/` on your own computer, opt in explicitly:

```bash
SPEC_TO_TEST_STORAGE=local streamlit run app.py
```

Only the exact value `local` (any case, spaces ignored) enables it; the
setting is read from the environment or Streamlit secrets, **not** from `.env`.
Delete `.spec_to_test_data/` to forget all saved work; files left there by
earlier versions are ignored in `session` mode. Any self-hosted shared
deployment (Docker, VM, other platforms) is covered too: do not set `local`.

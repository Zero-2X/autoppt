# Runtime environment

Run formal quality gates on Windows with Microsoft PowerPoint when possible.
Without PowerPoint COM export, the Gold release must remain `blocked`.

```powershell
cd <path-to-autoppt>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The Conda exports `environment.yml` and `environment.lock.yml` describe a Linux
environment named `autoppt`; they are not Windows installation recipes.
Use the venv commands above on Windows. Node.js/PptxGenJS are used by some editable composers.
Before a formal run, check the available backends:

```powershell
python autopptskills/scripts/check_editable_backends.py --json-out .codex-tmp/method-capabilities.json
```

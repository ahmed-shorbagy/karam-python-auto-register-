# Build customer ZIP (developer only)

The customer receives **KaramaAutomation.zip** — no Python, no `.bat`, no scripts.

## One-time on your PC

```powershell
cd "d:\web script python ( my implmented one)"
pip install -r requirements.txt
pip install pyinstaller
python -m playwright install chromium
```

1. Put correct Telegram settings in `register.ini` (or use template and edit after copy).
2. Run:

```powershell
python build_release.py
```

3. Deliver to customer:

```
release\KaramaAutomation.zip
```

(~300–500 MB because Chromium is bundled)

## Customer package contents

| Item | Purpose |
|------|---------|
| `KaramaStart.exe` | Main program — double-click |
| `TestTelegram.exe` | Test Telegram only |
| `register.ini` | Settings |
| `register_cases/` | Drop XML case files |
| `register_finished/` | Completed cases |
| `browsers/` | Required — do not delete |
| `دليل_المستخدم.txt` | Arabic user guide |
| `اقرأني.txt` | Quick start |

## Before each delivery

- [ ] Run `TestTelegram.exe` from the built folder
- [ ] Test one real case in `register_cases`
- [ ] Revoke/regenerate bot token if it was exposed
- [ ] Zip `release\KaramaAutomation` folder

## If build fails

- Install Visual C++ Redistributable on build machine
- Run `python -m playwright install chromium` again
- Delete `build/` and `dist/` folders and rebuild

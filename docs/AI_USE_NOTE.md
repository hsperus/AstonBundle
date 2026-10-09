# AI-use record (draft for the team's AI-use statement)

The DG4AGA brief asks for an AI-use statement naming the tool, purpose, affected component and how the output was checked. This file records what Claude produced, so the team can write that statement accurately. Edit it to match what the team actually did.

| Tool | Purpose | Affected component | How the team checked / changed it |
|---|---|---|---|
| Claude Design | UI design (screens, tokens, logo variants) | `AstonBundle-UI/`, `static/css/astonbundle.css` | *[team to fill in]* |
| Claude (Opus) | Wrote the Django code, templates, seed data, AI models, tests and README, based on the team's idea, flows and design | whole `astonbundle-web/` repository | *[team to fill in: code review, running tests, manual testing, changes made]* |
| OpenAI `gpt-image-1` (run by Claude) | Generated every product photo. Products named "AstonBundle …" were made with the team's own logo (`AstonBundle-UI/assets/logo-master.png`) as a reference image so it prints on the product. No Aston University logo or other third-party mark was used. | `catalog/seed_images/*.webp` (loaded by `python manage.py seed`) | *[team to fill in]* Prompts for each image are kept in `catalog/seed_images/_prompts.json`. |

Lecturer permission for this level of AI use: *[date and reference of the email/message]*.

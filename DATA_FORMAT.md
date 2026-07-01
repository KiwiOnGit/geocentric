# Geocentric 2.1 data formats

## Pretraining data

Accepted:

- `.txt`
- `.md`
- `.jsonl`
- `.json`
- `.csv`
- a directory containing those files

Pretraining is next-token prediction. The trainer will tokenize the text and build fixed-length causal chunks.

## Guided SFT data

Use JSONL with:

```json
{"instruction":"...","input":"optional context","response":"assistant answer"}
```

The SFT trainer masks prompt tokens so the model is trained mainly on the response.

## Desktop workspace inputs

The native app can attach or inspect common project files while running an agent job:

- Text/code: `.txt`, `.md`, `.json`, `.csv`, `.html`, `.css`, `.js`, `.ts`, `.swift`, `.py`, logs
- Images: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`
- Archives/documents: `.zip`, `.pdf`

Attachments are copied into the chat workspace. The agent should first define the objective, then use workspace tools such as `<read_file>`, `<write_file>`, `<run_command>`, or `<search>` when the user asks for file, command, project, or current web work.

---
name: mhtml-to-markdown
description: Use when converting saved web pages in .mhtml or .mht format into Markdown while preserving article structure, headings, images, captions, and readable layout
---

# MHTML to Markdown

Use this skill when the user wants a saved webpage converted from `.mhtml` or `.mht` into a Markdown document that keeps the article readable.

## Output

Create:
- one `.md` file
- one sibling `.assets` directory for extracted images

Preserve when possible:
- title and source metadata
- author, time, and location metadata
- heading hierarchy
- paragraph spacing
- figures and captions

## Workflow

1. Run `scripts/convert_mhtml_to_md.py` with the source file path.
2. By default, write output next to the source file unless the user asks for another location.
3. Review the generated Markdown and remove leftover site chrome or style-only markup if needed.
4. Tell the user where the `.md` file and `.assets` directory were written.

## Command

```bash
python3 skills/mhtml-to-markdown/scripts/convert_mhtml_to_md.py /absolute/path/to/file.mhtml
```

If the current working directory is not the repository root, use the full path to the script instead.

## Notes

- The script extracts the embedded HTML from the MHTML payload and avoids comments, recommendations, and other page chrome when it can isolate a main content area.
- It localizes article images into a sibling assets directory and rewrites image links to relative paths.
- It uses `pandoc`, so if conversion quality is poor or `pandoc` is missing, explain that clearly and stop.

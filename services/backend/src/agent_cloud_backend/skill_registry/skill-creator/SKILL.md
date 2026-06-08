---
name: skill-creator
description: "Author a new agent-cloud skill — scaffold a skill package (a directory with a valid SKILL.md and any helper scripts). Use when the user asks to create, scaffold, write, or design a new skill."
version: "1.0.0"
---

# skill-creator

Use this when the user wants to **create a new skill** for this agent platform. Your job is to
produce a *skill package*: a directory named after the skill, containing a `SKILL.md` (and any
helper scripts the skill needs), written into the working directory with the file tools
(`write_file` / `edit`).

## What a skill is here

A skill is a folder with a `SKILL.md`. Once a user installs and enables it for an agent, the
platform copies it into the agent's working directory at `.skills/<name>/` and injects only the
skill's **name + description + location** into the system prompt. The agent then **reads the
`SKILL.md` on demand** (with `read_file`) when a task matches the description — so the body can be
as long as needed without costing context until it's actually used (progressive disclosure).

Implication: the `description` is the *only* routing signal the model sees up front. Everything
else lives in the body and is paid for only when read.

## SKILL.md format

A `SKILL.md` is YAML frontmatter (between `---` lines) followed by a Markdown body.

Frontmatter fields:
- `name` (required) — lowercase, matches `^[a-z0-9][a-z0-9._-]*$`, no `..`, ≤ 64 chars. Must equal
  the directory name. Examples: `notion`, `pdf-tools`, `gh-issues`.
- `description` (required, non-empty) — one or two sentences: **what the skill does AND when to use
  it**, with concrete trigger words. This is what makes the model pick the skill, so be specific.
  Bad: "Helps with files." Good: "Convert and inspect PDFs (extract text, split, merge). Use when
  the user works with .pdf files."
- `version` (optional, string, default `"0.0.0"`) — e.g. `"1.0.0"`.
- `requires` (optional mapping) — declared dependencies, e.g. `requires: { bins: [pandoc] }`. Use it
  to document the CLIs/packages the skill expects in the sandbox.

Body guidance (the on-demand instructions):
- Lead with a one-line purpose, then the **exact steps/commands** to accomplish the task.
- Prefer concrete commands the agent can run with the `bash` tool over prose. Show real examples
  and expected output.
- Call out gotchas, required inputs, and how to verify success.
- Keep it focused on one capability; if it sprawls, split into multiple skills.

## Bundled helper files

Put any scripts/templates the skill needs **inside the skill directory** alongside `SKILL.md`. After
install they live at `.skills/<name>/...` in the working directory, so reference them by that path,
e.g. `bash .skills/<name>/scripts/run.sh`. Make scripts self-contained (no absolute paths; install
deps with `pip install --user` / `npm install -g` as the environment requires).

## Steps to create a skill

1. Pick a `name` (kebab-case, matches the regex above).
2. Create the directory and write `SKILL.md`:
   - `write_file` to `"<name>/SKILL.md"` with the frontmatter + body.
   - Add helper scripts under `"<name>/scripts/..."` if needed.
3. **Validate** before finishing:
   - Frontmatter parses as YAML and is between two `---` lines.
   - `name` matches `^[a-z0-9][a-z0-9._-]*$`, ≤ 64 chars, and equals the directory name.
   - `description` is present, non-empty, and says *what + when*.
4. Tell the user how to install it (the agent cannot self-install): either upload the folder as a
   `.zip` via the workspace's skill upload (if enabled), or have an operator drop the directory into
   the server's skill registry. Once installed and enabled for an agent, it appears in
   `<available_skills>`.

## Example: a minimal skill

`pdf-tools/SKILL.md`:

```markdown
---
name: pdf-tools
description: "Extract text from PDFs and split/merge pages. Use when the user works with .pdf files."
version: "1.0.0"
requires:
  bins: [python3]
---

# pdf-tools

Extract text:

    pip install --user pypdf
    python3 -c "import pypdf,sys; print('\n'.join(p.extract_text() for p in pypdf.PdfReader(sys.argv[1]).pages))" input.pdf

Split/merge: see pypdf's `PdfWriter`. Always confirm the output file exists before reporting done.
```

## Checklist before you finish
- [ ] Directory name == frontmatter `name`, valid pattern, ≤ 64 chars.
- [ ] `description` says what it does **and when to use it**, with trigger words.
- [ ] Body has concrete, runnable steps (not vague prose); examples included.
- [ ] Helper files (if any) are inside the skill dir and referenced via `.skills/<name>/...`.
- [ ] You told the user how to install/enable it.

# Academic Paper Polish Skill

Inspired by [gpt_academic](https://github.com/binary-husky/gpt_academic), this skill provides academic paper polishing, grammar checking, and language improvement for LaTeX papers.

## gpt_academic Setup (when network available)

```bash
# Clone and install
git clone https://github.com/binary-husky/gpt_academic.git
cd gpt_academic
pip install -r requirements.txt

# Configure API key in config.py
# Set API_KEY = "your-api-key"
# Set API_URL if using custom endpoint

# Launch
python main.py
```

Key features of gpt_academic applicable to this paper:
- **润色/Polish**: Improve academic English phrasing
- **语法检查/Grammar**: Find and fix grammar errors
- **中英互译/Translation**: Translate between Chinese and English
- **PDF总结/Summarize**: Extract key points from reference PDFs

## Native Claude Paper Polish

When invoked, this skill performs the following on the target LaTeX file:

### Polish Mode
1. Read the LaTeX file, preserving all LaTeX commands and math
2. Improve academic English:
   - Use precise technical vocabulary
   - Eliminate wordiness and redundancies
   - Ensure consistent tense and voice
   - Fix grammar and punctuation
3. Preserve all `\newcommand`, `\cite`, `\ref`, `\eqref`, `\label` commands
4. Keep equation formatting intact
5. Output the polished version

### Grammar Check Mode
1. Check for common LaTeX+English issues:
   - Missing articles (a, an, the)
   - Subject-verb agreement
   - Comma usage in equations
   - Consistent capitalization in section titles
2. Report findings with line numbers

### Consistency Check Mode
1. Verify all `\ref` and `\cite` references resolve
2. Check that all macros in `results_generated.tex` are used
3. Verify figure and table numbering is sequential
4. Check that all acronyms are defined on first use

## Usage

Invoke with: `/academic-polish <target-file> [mode: polish|grammar|consistency]`

Default mode is `polish`.

## Current Project Context

- Main paper: `technical-paper/main.tex`
- Sections: `technical-paper/sections/*.tex`
- Generated data: `technical-paper/results_generated.tex`
- Format: IEEE double-column, 2-page main content limit
- Submission: FPT'26 Track-A

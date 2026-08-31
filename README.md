# Resume ATS Analyzer

Compare two resumes side-by-side with an interactive HTML dashboard. Uses [Affinda](https://www.affinda.com/) to parse resume skills and [Gemini Flash](https://ai.google.dev/) to classify them into AI-generated taxonomy categories with weighted scoring.

## What It Does

1. **Parses** two PDF resumes via Affinda's resume parser API
2. **Extracts** the target job role from each resume
3. **Generates** a taxonomy of skill categories tailored to the role (via Gemini)
4. **Classifies** every skill into those categories with weighted point values
5. **Produces** a single self-contained HTML dashboard with:
   - KPI scorecards showing point deltas per category
   - Filterable skill tables (less/more/equal representation)
   - Interactive ignore checkboxes with live recalculation
   - Noise filtering for parser artifacts

The output HTML is fully self-contained — no external dependencies, works offline, shareable as a single file.

## Setup

### Prerequisites

- Python 3.10+
- An [Affinda API key](https://app.affinda.com/) (free tier available)
- A [Gemini API key](https://aistudio.google.com/apikey) (free tier available)

### Install

```bash
git clone https://github.com/omercanyy/resume-ats-analyzer.git
cd resume-ats-analyzer

# Optional: install certifi for proper SSL (recommended)
pip install certifi

# Configure API keys
cp .env.example .env
# Edit .env and add your AFFINDA_API_KEY and GEMINI_API_KEY
```

## Usage

### With Google Docs URLs (docs must be publicly shared)

```bash
python3 generate_report.py \
  --baseline "https://docs.google.com/document/d/YOUR_BASELINE_DOC_ID/edit" \
  --improved "https://docs.google.com/document/d/YOUR_IMPROVED_DOC_ID/edit"
```

### With local PDF files

```bash
python3 generate_report.py \
  --baseline-file ~/Documents/old_resume.pdf \
  --improved-file ~/Documents/new_resume.pdf
```

### Mix and match

```bash
python3 generate_report.py \
  --baseline "https://docs.google.com/document/d/ABC123/edit" \
  --improved-file ~/Documents/new_resume.pdf
```

### Custom output path

```bash
python3 generate_report.py \
  --baseline-file base.pdf \
  --improved-file new.pdf \
  -o ~/Desktop/comparison.html
```

### All options

```
usage: generate_report.py [-h] [--baseline DOC_ID] [--improved DOC_ID]
                          [--baseline-file PATH] [--improved-file PATH]
                          [-o PATH]

Options:
  --baseline DOC_ID       Google Doc/Drive ID or URL for the baseline resume
  --improved DOC_ID       Google Doc/Drive ID or URL for the improved resume
  --baseline-file PATH    Local PDF path for the baseline resume
  --improved-file PATH    Local PDF path for the improved resume
  -o, --output PATH       Output HTML path (default: ats_comparison.html)
```

The `--baseline` and `--improved` flags accept any of these formats:
- Raw ID: `1AqF9a4sGk9B_N4RIXe4vjFez52YEYZA6`
- Docs URL: `https://docs.google.com/document/d/1AqF9.../edit`
- Drive URL: `https://drive.google.com/file/d/1AqF9.../view`
- Share URL: `https://drive.google.com/open?id=1AqF9...`

## How It Works

### Two-Step AI Taxonomy

Instead of hardcoded skill categories, the tool uses a two-step Gemini process:

1. **Step 1 — Generate taxonomy**: Given the target role (e.g., "Lead SDET"), Gemini generates 6-8 weighted categories specific to that role (e.g., "Test Automation Frameworks ×5", "DevOps & CI/CD ×4", "Performance Testing ×3")

2. **Step 2 — Classify skills**: Each skill is classified into one of those categories with a reason, or filtered as `PARSER_NOISE`

Both steps use `temperature=0` and `seed=42` for **deterministic, reproducible results**.

### Scoring

Each skill earns points based on its category weight:

```
Skill Score = Category Weight × (1 if present, 0 if absent)
Total Score = Sum of all non-noise skill scores
Delta = (Improved - Baseline) / Baseline × 100%
```

### Caching

The tool caches aggressively to avoid redundant API calls:

| Cache | Location | What |
|---|---|---|
| Affinda responses | `.cache/affinda_*.json` | SHA-256 hash of PDF bytes → parsed resume |
| Taxonomy definitions | `.cache/taxonomy_def_*.json` | Role → category definitions (generated once) |
| Skill classifications | `.cache/taxonomy_*.json` | Skill → category mapping (incremental) |

Adding a new skill to a resume only classifies the **new** skill — existing classifications are served from cache.

To force a full reclassification:
```bash
rm .cache/taxonomy_*.json
python3 generate_report.py --baseline-file base.pdf --improved-file new.pdf
```

## Project Structure

```
resume-ats-analyzer/
├── generate_report.py   # Main pipeline (parse → classify → render)
├── config.py            # Environment loader, cache paths, API keys
├── .env.example         # Template for API keys
├── .env                 # Your API keys (gitignored)
├── .cache/              # All cached API responses (gitignored)
└── ats_comparison.html  # Generated dashboard (gitignored)
```

## License

MIT

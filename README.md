# Digital Detective

**Author:** Nikita Drõndin

Digital Detective is a command-line OSINT tool. It accepts a full name, an IP
address, a social-media username, or several parameters together. Results are
printed in the terminal and saved without overwriting earlier reports.

## Disclaimer

This software is an educational project created to demonstrate responsible
OSINT techniques. Use it only for lawful purposes and only with information
that is publicly accessible. Users are responsible for following applicable
laws, privacy requirements, and the terms of each data source. Search results
may be incomplete, outdated, or incorrect and must not be treated as verified
facts. The author is not responsible for misuse, unauthorized surveillance,
harassment, or damage resulting from use of this software.

## Features

- `-n/--name`: searches Wikidata and an official website for publicly listed
  address and phone information.
- `-ip/--ip`: returns location and ISP data cross-referenced through IPWhoIs
  and ipapi.
- `-un/--username`: checks GitHub, GitLab, Reddit, Instagram, X, TikTok,
  Facebook, Twitch, Pinterest, and Steam.
- Multiple search parameters can be combined in one command.
- A text report is always created; `--json` adds structured JSON output.
- Existing reports receive numeric suffixes instead of being overwritten.
- Network timeouts, unavailable sources and API errors are handled.

## Setup

Python 3.11 or later is recommended.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

The default providers do not require API keys. Optional endpoint settings are
shown in `.env.example`; real `.env` files are excluded by `.gitignore`.

## Usage

```text
python data_digger.py --help
python data_digger.py -n "Jane Example"
python data_digger.py -ip 8.8.8.8
python data_digger.py -un "@octocat"
python data_digger.py -n "Jane Example" -ip 8.8.8.8 -un janedoe --json
```

Reports are written to `reports` by default:

```text
reports/n_jane_example.txt
reports/ip_8_8_8_8.txt
reports/un_octocat.txt
reports/n_ip_un_jane_example.txt
```

A repeated search creates `n_jane_example1.txt`, then
`n_jane_example2.txt`. Use `--output-dir PATH` to select another directory.

## Docker

Docker is the only dependency when using a startup script.

Linux/macOS:

```bash
./run.sh -ip 8.8.8.8
```

Windows PowerShell:

```powershell
.\run.ps1 -SearchArguments @('-ip', '8.8.8.8')
```

Direct Docker commands:

```bash
docker build -t digital-detective .
docker run --rm -v "./reports:/reports" digital-detective -ip 8.8.8.8 --output-dir /reports
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The test suite covers CLI help and invalid input, name/IP/username searches,
cross-referencing, report naming, repeated files, JSON output, multiple search
parameters, public contact extraction and network retry behavior.

## Project structure

```text
data_digger.py                   CLI entry point
digital_detective/cli.py         argument parsing and orchestration
digital_detective/http_client.py HTTP access and error handling
digital_detective/search.py      APIs, scraping and validation
digital_detective/reports.py     terminal and file output
tests/                           automated tests
Dockerfile, run.sh, run.ps1      Docker startup
```

This implementation was written by Nikita Drõndin for the Digital Detective
assignment. The separate Mr.Holmes repository was used only as a feature
reference; its source code and branding are not included.

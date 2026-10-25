# ats-jobs

Pull every open job from a company's **Greenhouse, Lever, Ashby or SmartRecruiters** board, in one
schema, **without an API key or login**.

Each of these four applicant tracking systems publishes a public JSON feed for every company job
board: the same data the careers page shows. `ats-jobs` reads those feeds and prints jobs as JSON
lines (or CSV). One file, Python 3 standard library only.

## Usage

```bash
python3 ats_jobs.py lever:palantir                       # ats:slug
python3 ats_jobs.py https://jobs.ashbyhq.com/openai      # or the job board URL
python3 ats_jobs.py stripe                               # or a bare slug: tries all four ATS
python3 ats_jobs.py greenhouse:gitlab ashby:openai -k engineer --remote
python3 ats_jobs.py lever:palantir -l london --csv > palantir-london.csv
python3 ats_jobs.py ashby:openai --state seen.json       # only jobs opened or closed since last run
```

Output, one JSON object per job:

```json
{"ats": "ashby", "company": "openai", "id": "4ef5bf23-cf0e-4b97-a639-11f963c99b88", "title": "Software Engineer, Financial Engineering", "department": "Applied AI", "team": "Applied AI Engineering", "location": "San Francisco", "remote": true, "employment_type": "FullTime", "url": "https://jobs.ashbyhq.com/openai/4ef5bf23-cf0e-4b97-a639-11f963c99b88", "published_at": "2026-08-28T17:41:41.133+00:00"}
```

Fields the ATS does not publish are `null` (Greenhouse has no team or employment type, for example).
A per-company count goes to stderr, so stdout stays clean for `jq`.

## Finding the slug

It is the first path segment of the company's job board URL:

| ATS | Job board URL | Argument |
|---|---|---|
| Greenhouse | `job-boards.greenhouse.io/gitlab` | `greenhouse:gitlab` |
| Lever | `jobs.lever.co/palantir` (or `jobs.eu.lever.co/...`) | `lever:palantir` |
| Ashby | `jobs.ashbyhq.com/openai` | `ashby:openai` |
| SmartRecruiters | `jobs.smartrecruiters.com/Ubisoft2` | `smartrecruiters:Ubisoft2` |

If a careers page is on the company's own domain, open any job on it: the apply link usually
points at one of these hosts.

## Watch for new and closed jobs from cron

`--state FILE` remembers the job IDs seen on each board. Each run prints only jobs that appeared
since the previous run (`"status": "new"`) and jobs that disappeared (`"status": "closed"`), then
updates the file. The first run prints everything as new. A board that fails to load is skipped
and never reported as closed.

```bash
# every morning: new remote engineering roles at three companies, appended to a log
0 8 * * * cd ~/ats-jobs && python3 ats_jobs.py ashby:openai lever:palantir greenhouse:gitlab -k engineer --remote --state seen.json >> new-jobs.jsonl
```

## Tests

Offline, on saved responses from all four APIs:

```bash
python3 -m unittest discover tests
```

## Limits

- Only public job boards on these four ATS. Workday, iCIMS, Taleo and others are not covered.
- No job descriptions: the list endpoints are kept small. Follow `url` for the full text.
- Lever accounts in the EU region live on a separate host; `ats-jobs` tries it automatically.
- SmartRecruiters answers an unknown company with an empty list, so a company with zero open
  jobs there looks the same as one that does not exist.
- A bare slug is tried on Greenhouse, Lever, Ashby, SmartRecruiters in that order and the first
  board found wins. Use `ats:slug` if a company has boards on two systems.
- macOS with python.org Python: if you get `CERTIFICATE_VERIFY_FAILED`, run
  `/Applications/Python 3.x/Install Certificates.command` once, or prefix the command with
  `SSL_CERT_FILE=/etc/ssl/cert.pem`.

Be polite with request rates, and respect each site's terms and the law where you work.

## Hosted version

If you need hundreds of companies on a schedule without keeping a machine on, with job descriptions,
retries, proxies and per-company hiring signals (top departments, remote share, roles posted in
the last 30 days), I run a hosted version on Apify:
[Greenhouse, Lever & Ashby Job Scraper](https://apify.com/ax_dev/greenhouse-lever-ashby-job-scraper)
(paid per result, needs an Apify account). The script above stays free and does not depend on it.

## License

MIT

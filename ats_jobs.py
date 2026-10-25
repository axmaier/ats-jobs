#!/usr/bin/env python3
"""Pull open jobs from Greenhouse, Lever, Ashby and SmartRecruiters job boards.

All four publish a public JSON feed for every company job board; no API key or login.
Prints one JSON object per job, in one schema for all four. Python 3 standard library only.
"""
import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = "ats-jobs/1.0 (+https://github.com/axmaier/ats-jobs)"
ATS = ("greenhouse", "lever", "ashby", "smartrecruiters")
FIELDS = ("ats", "company", "id", "title", "department", "team", "location", "remote",
          "employment_type", "url", "published_at")
LEVER_HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")  # EU accounts 404 on the global host

URL_PATTERNS = (
    (r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w.-]+)", "greenhouse"),
    (r"boards-api\.greenhouse\.io/v1/boards/([\w.-]+)", "greenhouse"),
    (r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)", "lever"),
    (r"jobs\.ashbyhq\.com/([\w.%-]+)", "ashby"),
    (r"(?:jobs|careers)\.smartrecruiters\.com/([\w.-]+)", "smartrecruiters"),
)


def parse_target(arg):
    """'lever:palantir', a job board URL, or a bare slug -> (ats or None, company)."""
    for pattern, ats in URL_PATTERNS:
        m = re.search(pattern, arg)
        if m:
            return ats, m.group(1)
    if ":" in arg and "/" not in arg:
        ats, company = arg.split(":", 1)
        if ats.lower() not in ATS:
            raise ValueError(f"unknown ATS {ats!r}, expected one of: {', '.join(ATS)}")
        return ats.lower(), company
    if re.fullmatch(r"[\w.-]+", arg):
        return None, arg
    raise ValueError(f"cannot read a company from {arg!r}")


def get_json(url):
    """Parsed JSON, or None on 404."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def iso_ms(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms else None


def job(**kw):
    return {f: kw.get(f) for f in FIELDS}


# --- parsers: API response -> jobs (no network, tested offline) -----------

def parse_greenhouse(company, data, departments=None):
    dept = {}
    for d in (departments or {}).get("departments", []):
        for j in d.get("jobs", []):
            dept[j["id"]] = d["name"]
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name")
        out.append(job(ats="greenhouse", company=company, id=str(j["id"]), title=j.get("title"),
                       department=dept.get(j["id"]), location=loc,
                       remote=bool(re.search("remote", loc or "", re.I)),
                       url=j.get("absolute_url"),
                       published_at=j.get("first_published") or j.get("updated_at")))
    return out


def parse_lever(company, data):
    out = []
    for j in data:
        c = j.get("categories") or {}
        out.append(job(ats="lever", company=company, id=j["id"], title=j.get("text"),
                       department=c.get("department"), team=c.get("team"), location=c.get("location"),
                       remote=(j.get("workplaceType") or "").lower() == "remote"
                       or bool(re.search("remote", c.get("location") or "", re.I)),
                       employment_type=c.get("commitment"),
                       url=j.get("hostedUrl") or j.get("applyUrl"), published_at=iso_ms(j.get("createdAt"))))
    return out


def parse_ashby(company, data):
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append(job(ats="ashby", company=company, id=j["id"], title=j.get("title"),
                       department=j.get("department"), team=j.get("team"), location=j.get("location"),
                       remote=bool(j.get("isRemote")), employment_type=j.get("employmentType"),
                       url=j.get("jobUrl") or j.get("applyUrl"), published_at=j.get("publishedAt")))
    return out


def parse_smartrecruiters(company, data):
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        where = loc.get("fullLocation") or ", ".join(
            x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x) or None
        out.append(job(ats="smartrecruiters", company=company, id=str(j["id"]), title=j.get("name"),
                       department=(j.get("department") or {}).get("label"),
                       team=(j.get("function") or {}).get("label"), location=where,
                       remote=bool(loc.get("remote")),
                       employment_type=(j.get("typeOfEmployment") or {}).get("label"),
                       url=f"https://jobs.smartrecruiters.com/{company}/{j['id']}",
                       published_at=j.get("releasedDate")))
    return out


# --- fetchers: one company -> jobs, or None if the board does not exist ----

def fetch_greenhouse(company):
    base = f"https://boards-api.greenhouse.io/v1/boards/{company}"
    data = get_json(f"{base}/jobs")
    if data is None:
        return None
    try:
        departments = get_json(f"{base}/departments")
    except urllib.error.URLError:
        departments = None
    return parse_greenhouse(company, data, departments)


def fetch_lever(company):
    for host in LEVER_HOSTS:
        data = get_json(f"{host}/v0/postings/{company}?mode=json")
        if data is not None:
            return parse_lever(company, data)
    return None


def fetch_ashby(company):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company}")
    return None if data is None else parse_ashby(company, data)


def fetch_smartrecruiters(company, limit=100):
    out, offset = [], 0
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
                        f"?limit={limit}&offset={offset}")
        if data is None:
            return None if offset == 0 else out
        page = parse_smartrecruiters(company, data)
        out += page
        offset += len(page)
        if len(page) < limit or offset >= data.get("totalFound", 0):
            # SmartRecruiters answers 200 with zero postings for unknown companies
            return out if out else None


FETCH = {"greenhouse": fetch_greenhouse, "lever": fetch_lever,
         "ashby": fetch_ashby, "smartrecruiters": fetch_smartrecruiters}


def fetch(ats, company):
    """(ats, jobs) for the first board that exists, trying all four for a bare slug."""
    for name in ([ats] if ats else ATS):
        jobs = FETCH[name](company)
        if jobs is not None:
            return name, jobs
    return None, None


def matches(j, keyword=None, location=None, remote=False):
    if keyword and not re.search(re.escape(keyword), " ".join(
            str(j[f] or "") for f in ("title", "department", "team")), re.I):
        return False
    if location and not re.search(re.escape(location), j["location"] or "", re.I):
        return False
    return not remote or j["remote"]


def diff(jobs_by_board, state):
    """Jobs not in state get status 'new'; ids that left a board get status 'closed'.

    Only boards fetched in this run are compared, so a failed request never reports closures.
    Updates state in place: {"ats:company": {id: job}}.
    """
    out = []
    for board, jobs in jobs_by_board.items():
        before = state.get(board, {})
        now = {j["id"]: j for j in jobs}
        out += [dict(j, status="new") for i, j in now.items() if i not in before]
        out += [dict(j, status="closed") for i, j in before.items() if i not in now]
        state[board] = now
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("companies", nargs="+", metavar="COMPANY",
                   help="ats:slug (lever:palantir), a job board URL, or a bare slug to try all four")
    p.add_argument("-k", "--keyword", help="only jobs whose title/department/team contains this")
    p.add_argument("-l", "--location", help="only jobs whose location contains this")
    p.add_argument("--remote", action="store_true", help="only remote jobs")
    p.add_argument("--state", metavar="FILE",
                   help="print only jobs opened or closed since the previous run (adds 'status')")
    p.add_argument("--csv", action="store_true", help="CSV instead of JSON lines")
    a = p.parse_args(argv)

    boards, failed = {}, 0
    for arg in a.companies:
        try:
            ats, company = parse_target(arg)
            ats, jobs = fetch(ats, company)
        except (ValueError, urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"{arg}: {e}", file=sys.stderr)
            failed += 1
            continue
        if jobs is None:
            print(f"{arg}: no job board found on {', '.join(ATS)}", file=sys.stderr)
            failed += 1
            continue
        boards[f"{ats}:{company}"] = jobs
        print(f"{ats}:{company}: {len(jobs)} open jobs", file=sys.stderr)

    if a.state:
        try:
            with open(a.state) as f:
                state = json.load(f)
        except FileNotFoundError:
            state = {}
        rows = diff(boards, state)
        with open(a.state, "w") as f:
            json.dump(state, f)
    else:
        rows = [j for jobs in boards.values() for j in jobs]
    rows = [j for j in rows if matches(j, a.keyword, a.location, a.remote)]

    if a.csv:
        cols = FIELDS + (("status",) if a.state else ())
        w = csv.DictWriter(sys.stdout, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    else:
        for j in rows:
            print(json.dumps(j, ensure_ascii=False))
    return 1 if failed and not boards else 0


if __name__ == "__main__":
    sys.exit(main())

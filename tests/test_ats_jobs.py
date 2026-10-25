import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ats_jobs as A  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


class ParseTarget(unittest.TestCase):
    def test_prefixed(self):
        self.assertEqual(A.parse_target("lever:palantir"), ("lever", "palantir"))
        self.assertEqual(A.parse_target("Ashby:openai"), ("ashby", "openai"))

    def test_urls(self):
        cases = {
            "https://job-boards.greenhouse.io/gitlab": ("greenhouse", "gitlab"),
            "https://boards.greenhouse.io/gitlab/jobs/123": ("greenhouse", "gitlab"),
            "https://boards.greenhouse.io/embed/job_board?for=gitlab": ("greenhouse", "gitlab"),
            "https://jobs.lever.co/palantir/abc": ("lever", "palantir"),
            "https://jobs.eu.lever.co/prima": ("lever", "prima"),
            "https://jobs.ashbyhq.com/openai": ("ashby", "openai"),
            "https://jobs.smartrecruiters.com/Ubisoft2/744000157563150": ("smartrecruiters", "Ubisoft2"),
        }
        for url, want in cases.items():
            self.assertEqual(A.parse_target(url), want, url)

    def test_bare_slug_and_errors(self):
        self.assertEqual(A.parse_target("stripe"), (None, "stripe"))
        with self.assertRaises(ValueError):
            A.parse_target("workday:acme")
        with self.assertRaises(ValueError):
            A.parse_target("https://example.com/careers")


class Parsers(unittest.TestCase):
    def check(self, jobs, ats, company):
        self.assertEqual(len(jobs), 3)
        for j in jobs:
            self.assertEqual(tuple(j), A.FIELDS)
            self.assertEqual((j["ats"], j["company"]), (ats, company))
            self.assertTrue(j["id"] and j["title"] and j["url"].startswith("https://"))
            self.assertIsInstance(j["remote"], bool)
            self.assertRegex(j["published_at"], r"^\d{4}-\d\d-\d\dT")

    def test_greenhouse(self):
        data = load("greenhouse.json")
        first = data["jobs"][0]["id"]
        depts = {"departments": [{"name": "Sales", "jobs": [{"id": first}]}]}
        jobs = A.parse_greenhouse("gitlab", data, depts)
        self.check(jobs, "greenhouse", "gitlab")
        self.assertEqual(jobs[0]["department"], "Sales")
        self.assertEqual(jobs[0]["location"], "Remote, France")
        self.assertTrue(jobs[0]["remote"])

    def test_lever(self):
        self.check(A.parse_lever("palantir", load("lever.json")), "lever", "palantir")

    def test_ashby_skips_unlisted(self):
        data = load("ashby.json")
        self.check(A.parse_ashby("openai", data), "ashby", "openai")
        data["jobs"][0]["isListed"] = False
        self.assertEqual(len(A.parse_ashby("openai", data)), 2)

    def test_smartrecruiters(self):
        jobs = A.parse_smartrecruiters("Ubisoft2", load("smartrecruiters.json"))
        self.check(jobs, "smartrecruiters", "Ubisoft2")
        self.assertEqual(jobs[0]["location"], "Quebec City, QC, Canada")


class Fetch(unittest.TestCase):
    def test_lever_falls_back_to_eu(self):
        calls = []

        def fake(url):
            calls.append(url)
            return None if "api.lever.co" in url else load("lever.json")

        with mock.patch.object(A, "get_json", fake):
            self.assertEqual(len(A.fetch_lever("prima")), 3)
        self.assertEqual([c.split("/v0")[0] for c in calls], list(A.LEVER_HOSTS))

    def test_bare_slug_tries_each_ats(self):
        def fake(url):
            return load("ashby.json") if "ashbyhq" in url else None

        with mock.patch.object(A, "get_json", fake):
            ats, jobs = A.fetch(None, "openai")
        self.assertEqual((ats, len(jobs)), ("ashby", 3))

    def test_smartrecruiters_empty_means_not_found(self):
        with mock.patch.object(A, "get_json", lambda url: {"totalFound": 0, "content": []}):
            self.assertIsNone(A.fetch_smartrecruiters("nosuchco"))


class StateAndFilters(unittest.TestCase):
    def test_diff_new_then_closed(self):
        jobs = A.parse_ashby("openai", load("ashby.json"))
        state = {}
        first = A.diff({"ashby:openai": jobs}, state)
        self.assertEqual([j["status"] for j in first], ["new"] * 3)
        self.assertEqual(A.diff({"ashby:openai": jobs}, state), [])
        second = A.diff({"ashby:openai": jobs[1:]}, state)
        self.assertEqual([(j["id"], j["status"]) for j in second], [(jobs[0]["id"], "closed")])

    def test_diff_ignores_boards_not_fetched(self):
        state = {"lever:palantir": {"x": A.job(id="x")}}
        self.assertEqual(A.diff({}, state), [])
        self.assertIn("x", state["lever:palantir"])

    def test_matches(self):
        j = A.job(title="Senior Backend Engineer", department="Platform", location="Berlin", remote=False)
        self.assertTrue(A.matches(j, keyword="backend"))
        self.assertFalse(A.matches(j, keyword="sales"))
        self.assertTrue(A.matches(j, location="berlin"))
        self.assertFalse(A.matches(j, remote=True))

    def test_main_state_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(A, "get_json", lambda url: load("ashby.json") if "ashbyhq" in url else None), \
                mock.patch("sys.stdout") as out, mock.patch("sys.stderr"):
            path = os.path.join(d, "seen.json")
            self.assertEqual(A.main(["ashby:openai", "--state", path]), 0)
            printed = "".join(c.args[0] for c in out.write.call_args_list)
            self.assertEqual(printed.count('"status": "new"'), 3)
            self.assertEqual(len(json.load(open(path))["ashby:openai"]), 3)


if __name__ == "__main__":
    unittest.main()

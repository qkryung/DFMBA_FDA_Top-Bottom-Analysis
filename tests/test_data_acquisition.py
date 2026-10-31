"""Regression checks for document-selection bugs found in the real SEC corpus."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from topbottom.data import earnings_exhibit, exclusion_reason


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url):
        self.requested.append(url)
        return self.pages[url].encode("utf-8")


class EarningsSelectionRegression(unittest.TestCase):
    def test_selects_ex99_2_when_ex99_1_is_a_statistical_supplement(self):
        accession = "0000000123-24-000001"
        directory = "https://www.sec.gov/Archives/edgar/data/123/000000012324000001/"
        index = directory + accession + "-index.html"
        supplement, release = directory + "supplement.htm", directory + "release.htm"
        table = """<table>
          <tr><td>2</td><td>EX-99.1</td><td><a href="supplement.htm">supplement.htm</a></td><td>EX-99.1</td></tr>
          <tr><td>3</td><td>EX-99.2</td><td><a href="release.htm">release.htm</a></td><td>EX-99.2</td></tr>
        </table>"""
        # SEC uses absolute archive paths in document links.
        table = table.replace('href="supplement.htm"', f'href="{supplement}"').replace('href="release.htm"', f'href="{release}"')
        client = FakeClient({index: table,
                             supplement: "<p>Example Corp Supplemental Information First Quarter 2024</p>" + "<p>Net income and quarterly revenue.</p>" * 50,
                             release: "<h1>Example Corp Reports First Quarter Results</h1>" + "<p>Revenue and net income increased in the first quarter.</p>" * 50})
        source, _ = earnings_exhibit(client, 123, {"accessionNumber": accession, "primaryDocument": "primary.htm"})
        self.assertEqual(source, release)
        self.assertLess(client.requested.index(supplement), client.requested.index(release))

    def test_investor_day_mention_does_not_exclude_a_real_earnings_release(self):
        text = ("Caterpillar Inc. Fourth Quarter Earnings Release. Caterpillar Reports Fourth-Quarter and Full-Year Results. "
                "Full-year operating profit margin was within the 2019 Investor Day target range.")
        self.assertIsNone(exclusion_reason(text, "https://www.sec.gov/example/earnings.htm"))
        self.assertIsNotNone(exclusion_reason("Example Corporation Analyst Meeting Presentation and Q&A Session. " * 10,
                                             "https://www.sec.gov/example/analyst.htm"))


if __name__ == "__main__":
    unittest.main()

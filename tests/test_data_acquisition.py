"""Regression checks for document-selection bugs found in the real SEC corpus."""
import sys
import unittest
import json
import tempfile
import os
from unittest.mock import patch
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from topbottom.data import earnings_exhibit, exclusion_reason, load_universe, collect_firms, collect_fomc, extract_text, extract_text_reference, extract_earnings_section, conservative_ir_available_at, write_csv_atomic


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url):
        self.requested.append(url)
        return self.pages[url].encode("utf-8")


class EarningsSelectionRegression(unittest.TestCase):
    def test_closed_reviewed_filing_does_not_select_another_unverified_exhibit(self):
        client = FakeClient({})
        accession = '0000000123-24-000099'
        with patch('topbottom.data.source_recovery', return_value={'closed_unverified_filings': {accession: {'reason': 'Known alternatives are financial tables; no verified narrative'}}}):
            with self.assertRaisesRegex(ValueError, 'Reviewed filing excluded'):
                earnings_exhibit(client, 123, {'accessionNumber': accession})
        self.assertEqual(client.requested, [])

    def test_atomic_csv_retries_transient_windows_lock_without_partial_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'checkpoint.csv'
            path.write_text('value\nold\n',encoding='utf-8')
            real_replace=os.replace
            calls=[]
            def briefly_locked(source,destination):
                calls.append(1)
                if len(calls)==1:
                    self.assertEqual(path.read_text(encoding='utf-8'),'value\nold\n')
                    raise PermissionError('Transient reader lock')
                return real_replace(source,destination)
            with patch('topbottom.data.os.replace',side_effect=briefly_locked),patch('topbottom.data.time.sleep'):
                write_csv_atomic(pd.DataFrame({'value':['new']}),path)
            self.assertEqual(pd.read_csv(path).value.tolist(),['new'])
            self.assertEqual(len(calls),2)

    def test_date_only_ir_waits_for_new_york_midnight_and_later_sec_acceptance(self):
        self.assertEqual(conservative_ir_available_at('2022-04-28T15:00:00Z','2022-04-28'),'2022-04-29T04:00:00+00:00')
        self.assertEqual(conservative_ir_available_at('2022-01-28T15:00:00Z','2022-01-28'),'2022-01-29T05:00:00+00:00')
        self.assertEqual(conservative_ir_available_at('2022-04-29T15:00:00Z','2022-04-28'),'2022-04-29T15:00:00+00:00')

    def test_call_heading_does_not_exclude_a_substantive_guidance_update(self):
        update='DANAHER PROVIDES UPDATE ON FIRST QUARTER FINANCIAL PERFORMANCE AND SCHEDULES FIRST QUARTER EARNINGS CONFERENCE CALL. The company expects revenue growth of 3 percent.'
        self.assertIsNone(exclusion_reason(update,'https://example.com/update.htm'))
        self.assertIsNotNone(exclusion_reason('Company Fourth Quarter Earnings Conference Call. Forward-looking statements and discussion slides.','https://example.com/deck.htm'))

    def test_crh_embedded_release_excludes_cover_and_appended_interim_report(self):
        announcement='2017 Interim Results Key Points. Revenue and EBITDA increased. Chief Executive discussed the outlook.'
        original='6-K CRH public limited company. Regulation S-T Rule 101(b)(7):___ '+announcement+' Condensed Consolidated Income Statement financial statements and detailed notes.'
        self.assertEqual(extract_earnings_section(original),announcement)
        no_boundary=original.split(' Condensed Consolidated')[0]
        self.assertEqual(extract_earnings_section(no_boundary),no_boundary)
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

    def test_frozen_snapshot_does_not_refetch_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data/reference").mkdir(parents=True)
            expected = pd.DataFrame([{"ticker": "OLD", "company": "Fixed issuer", "sector": "Industrials", "cik": 123}])
            expected.to_csv(root / "data/reference/universe_snapshot.csv", index=False)
            client = FakeClient({})
            pd.testing.assert_frame_equal(load_universe(root, client), expected)
            self.assertEqual(client.requested, [])

    def test_completed_issuer_checkpoint_recovers_missing_aggregate_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in ("configs", "data/raw/issuer_checkpoints", "data/raw/http", "data/reference", "data/processed"):
                (root / folder).mkdir(parents=True, exist_ok=True)
            (root / "configs/research.json").write_text(json.dumps({"pilot_tickers": []}), encoding="utf-8")
            company = dict(ticker="FIX", company="Fixed issuer", sector="Industrials", cik=123, current_snapshot_cik=123)
            row = dict(ticker="FIX", doc_id="sec_123_test", published_at="2020-01-01T12:00:00Z", publication_date="2020-01-01")
            saved = dict(status=dict(ticker="FIX", status="completed", documents=1), records=[row], failures=[])
            (root / "data/raw/issuer_checkpoints/123_2016_2025.json").write_text(json.dumps(saved), encoding="utf-8")
            client = FakeClient({})
            client.cache, client.interval, client.requests_made = root / "data/raw/http", .25, 0
            with patch("topbottom.data.collect_company", side_effect=AssertionError("Checkpoint must prevent network recollection")), patch("topbottom.data.write_coverage"):
                records, failures = collect_firms(root, client, None, pd.DataFrame([company]), 2016, 2025)
            self.assertEqual(records, [row])
            self.assertEqual(failures, [])
            self.assertEqual(pd.read_csv(root / "data/processed/firm_scores.csv").doc_id.tolist(), [row["doc_id"]])

    def test_fast_parser_preserves_text_tails_embedded_release_and_content_cache(self):
        samples = [
            b'<html><body><p>Quarterly <b>earnings</b> grew.</p><script>discard();</script>Remaining tail<p>Revenue rose.</p></body></html>',
            b'<html><body>ATTACHMENT I IBM REPORTS FIRST QUARTER RESULTS<p>Revenue increased.</p>ATTACHMENT II SLIDES</body></html>',
            b'<html><body><p>Reports results &#151; quarterly revenue &#149; earnings.</p></body></html>'
        ]
        for content in samples:
            self.assertEqual(extract_text(content), extract_text_reference(content))
        self.assertNotEqual(extract_text(samples[0]), extract_text(samples[0].replace(b'grew', b'declined')))

    def test_zero_padded_first_exhibit_is_ranked_before_later_tables(self):
        accession="0000000123-24-000002"
        directory="https://www.sec.gov/Archives/edgar/data/123/000000012324000002/"
        index=directory+accession+"-index.html"
        first,last=directory+"a.htm",directory+"z.htm"
        rows=f'<tr><td>1</td><td>EXHIBIT99.01</td><td><a href="{first}">a.htm</a></td><td>EX-99.01</td></tr><tr><td>2</td><td>EXHIBIT99.07</td><td><a href="{last}">z.htm</a></td><td>EX-99.07</td></tr>'
        text='<p>Company Reports Quarterly Earnings Results. Revenue and net income increased compared with the prior quarter.</p>'*50
        client=FakeClient({index:'<table>'+rows+'</table>',first:text,last:text})
        source,_=earnings_exhibit(client,123,dict(accessionNumber=accession,primaryDocument='primary.htm'))
        self.assertEqual(source,first)
        self.assertNotIn(last,client.requested)

    def test_results_notice_is_not_the_substantive_shareholder_letter(self):
        notice=('Company announces first quarter financial results and posted a letter to its shareholders on its Investor Relations website. '
                'The conference call will discuss results and a replay will be available online. About the company: it provides software services worldwide. ')
        self.assertIsNotNone(exclusion_reason(notice,'https://example.com/release.htm'))
        self.assertIsNotNone(exclusion_reason(notice.replace(' ', '\n'),'https://example.com/release.htm'))
        actual=notice+' Quarterly revenue of $120 million increased from $100 million last year.'
        self.assertIsNone(exclusion_reason(actual,'https://example.com/release.htm'))

    def test_are_combined_document_requires_both_verified_section_boundaries(self):
        earnings='Alexandria Real Estate Equities, Inc. Reports First Quarter Results. Quarterly earnings and guidance follow.'
        original='SUPPLEMENTAL INFORMATION Cover and table of contents. '+earnings+' SUPPLEMENTAL INFORMATION Company Profile More tables.'
        self.assertEqual(extract_earnings_section(original),earnings)
        incomplete='SUPPLEMENTAL INFORMATION Cover and table of contents. '+earnings
        self.assertEqual(extract_earnings_section(incomplete),incomplete)

    def test_fomc_publication_year_includes_prior_december_meeting(self):
        class Score:
            def score(self, text):
                return {"word_count": 120, "sentence_count": 5}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for folder in ("data/processed", "data/raw/text", "data/raw/document_records", "data/raw/http"):
                (root/folder).mkdir(parents=True)
            base='https://www.federalreserve.gov'
            pages={base+'/monetarypolicy/fomchistorical2015.htm':'<p><a href="/monetarypolicy/fomcminutes20151216.htm">Minutes</a> Released January 06, 2016</p>',
                   base+'/monetarypolicy/fomchistorical2016.htm':'<p><a href="/monetarypolicy/fomcminutes20161214.htm">Minutes</a> Released January 04, 2017</p>',
                   base+'/monetarypolicy/fomcminutes20151216.htm':'<p>Staff Review of the Economic Situation. Employment improved and prices remained stable.</p><h2>Committee Policy Action</h2>'}
            rows=collect_fomc(root,FakeClient(pages),Score(),2016,2016)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['publication_date'],'2016-01-06')
            self.assertEqual(rows[0]['meeting_date'],'2015-12-16')
            self.assertEqual(rows[0]['published_at'],'2016-01-06T19:00:00+00:00')

    def test_reviewed_hal_and_frt_embedded_sections_require_both_boundaries(self):
        hal='HALLIBURTON ANNOUNCES FIRST QUARTER RESULTS. Revenue increased.'
        text='8-K cover. The text of the Press Release is as follows: FOR IMMEDIATE RELEASE '+hal+' SIGNATURES Pursuant to the requirements of the Securities Exchange Act.'
        self.assertEqual(extract_earnings_section(text),hal)
        frt='Federal Realty Investment Trust Reports First Quarter Results. Earnings increased.'
        text='Supplemental Information cover. '+frt+' Federal Realty Investment Trust Consolidated Income Statements Tables.'
        self.assertEqual(extract_earnings_section(text),frt)
        incomplete='Supplemental Information cover. '+frt
        self.assertEqual(extract_earnings_section(incomplete),incomplete)

    def test_nxp_embedded_release_starts_after_signature_not_quoted_cover_title(self):
        release = 'NXP Semiconductors Reports Fourth Quarter 2019 Results. Revenue increased this quarter.'
        text = '6-K cover. This report contains '+release+' SIGNATURES Pursuant to the requirements. NXP CFO signed. '+release
        self.assertEqual(extract_earnings_section(text), release)
        without_release = '6-K cover. This report contains '+release+' SIGNATURES Pursuant to the requirements. NXP CFO signed.'
        self.assertEqual(extract_earnings_section(without_release), without_release)

    def test_nxp_numbered_6k_exhibit_requires_quarterly_issuer_heading(self):
        accession='0000000123-24-000003'
        directory='https://www.sec.gov/Archives/edgar/data/1413447/000000012324000003/'
        index=directory+accession+'-index.html'
        release=directory+'release.htm'
        rows=f'<tr><td>1</td><td>EX-1</td><td><a href="{release}">release.htm</a></td><td>EX-1</td></tr>'
        text='<p>NXP Semiconductors Reports First Quarter 2024 Results.</p>'+'<p>Revenue and net income increased compared with the prior quarter.</p>'*50
        client=FakeClient({index:'<table>'+rows+'</table>',release:text})
        source,_=earnings_exhibit(client,1413447,dict(accessionNumber=accession,primaryDocument='primary.htm',form='6-K'))
        self.assertEqual(source,release)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from unittest.mock import patch

import websites as w


def posting(**changes):
    value = {'@type': 'JobPosting', 'title': 'Python engineer',
             'description': '<p>Build Python services and maintain reliable systems.</p>' * 6,
             'hiringOrganization': {'name': 'Example'}, 'datePosted': '2026-11-01',
             'jobLocation': [{'address': {'addressLocality': 'Berlin', 'addressCountry': 'DE'}}]}
    return dict(value, **changes)


class WebsiteTests(unittest.TestCase):
    def test_nextlevel_country_selection_shares_budget_and_identity(self):
        def fake(site, cache, limit, listing=None, deadline=None):
            return [dict(id='same', title='Same role')], []
        with patch.object(w, '_fetch', side_effect=fake) as fetch:
            jobs, _ = w.fetch('nextleveljobs', limit=3, countries=['de', 'nl'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual([call.args[2] for call in fetch.call_args_list], [2, 1])
        self.assertEqual([call.args[3] for call in fetch.call_args_list], ['https://nextleveljobs.eu/country/de', 'https://nextleveljobs.eu/country/nl'])
        self.assertEqual(fetch.call_args_list[0].kwargs['deadline'], fetch.call_args_list[1].kwargs['deadline'])
        with patch.object(w, '_fetch', side_effect=[ValueError('Blocked'), ([{'id': 'nl'}], [])]):
            jobs, warnings = w.fetch('nextleveljobs', countries=['de', 'nl'])
        self.assertEqual(jobs[0]['id'], 'nl')
        self.assertIn('Germany', warnings[0])

    def test_remote_applicant_country_is_preserved(self):
        post = posting(jobLocationType='TELECOMMUTE', applicantLocationRequirements={'name': 'Netherlands'})
        self.assertIn('Eligible country: Netherlands', w.normalize(post, 'https://example.com/job', 'test')['location'])

    def test_custom_structured_page_feed_and_query_links(self):
        spec = w.custom_spec('My source', 'https://example.com/search?q=python')
        url = 'https://example.com/job?id=123'
        text = '<script type="application/ld+json">' + json.dumps(posting(url=url)) + '</script>'
        with patch.object(w, 'read_public', return_value=text):
            jobs, _ = w.fetch_custom(spec)
        self.assertEqual(jobs[0]['url'], url)
        feed = '<rss><channel><item><link>' + url + '</link></item></channel></rss>'
        with patch.object(w, 'read_public', side_effect=[feed, text]), patch.object(w.time, 'sleep'):
            jobs, _ = w.fetch_custom(spec)
        self.assertEqual(jobs[0]['company'], 'Example')
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="' + url + '"/></entry></feed>'
        with patch.object(w, 'read_public', side_effect=[atom, text]), patch.object(w.time, 'sleep'):
            self.assertEqual(len(w.fetch_custom(spec)[0]), 1)

    def test_custom_unsupported_and_private_networks(self):
        with patch.object(w, 'read_public', return_value='<p>Only short excerpts</p>'):
            with self.assertRaisesRegex(ValueError, 'No complete structured jobs'):
                w.fetch_custom(w.custom_spec('Search', 'https://example.com/jobs'))
        for host in ('127.0.0.1', '169.254.169.254', '10.0.0.2', '::1', '224.0.0.1'):
            with patch.object(w.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', (host, 443))]), patch.object(w.socket, 'socket') as connect:
                with self.assertRaises(ValueError):
                    w.PublicConnection('example.com', timeout=1).connect()
                connect.assert_not_called()
        for url in ('http://example.com', 'https://localhost/x', 'https://user@example.com/x', 'https://example.com:443/x'):
            with self.assertRaises(ValueError):
                w.custom_spec('Name', url)

    def test_custom_full_feed_and_discovery(self):
        content = 'Maintain reliable Python services. ' * 8
        feed = '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item><title>Engineer @ Example</title><link>https://example.com/jobs/1</link><content:encoded><![CDATA[' + content + ']]></content:encoded></item></channel></rss>'
        html = '<html><head><link rel="alternate" type="application/rss+xml" href="/rss"/></head><body></body></html>'
        with patch.object(w, 'read_public', side_effect=[html, feed]) as read:
            jobs, _ = w.fetch_custom(w.custom_spec('Feed', 'https://example.com/'))
        self.assertEqual(jobs[0]['company'], 'Example')
        self.assertEqual(jobs[0]['description'], content.strip())
        self.assertEqual(read.call_count, 2)

    def test_public_connection_pins_address_and_tls_hostname(self):
        raw = unittest.mock.MagicMock()
        context = unittest.mock.MagicMock()
        address = ('93.184.216.34', 443)
        with patch.object(w.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', address)]) as resolve, patch.object(w.socket, 'socket', return_value=raw), patch.object(w.ssl, 'create_default_context', return_value=context):
            w.PublicConnection('example.com', timeout=15).connect()
        self.assertEqual(resolve.call_count, 1)
        raw.connect.assert_called_once_with(address)
        context.wrap_socket.assert_called_once_with(raw, server_hostname='example.com')

    def test_custom_redirects_revalidate_and_limit_requests(self):
        connection = unittest.mock.MagicMock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'http://127.0.0.1/'
        with patch.object(w, 'PublicConnection', return_value=connection) as connect:
            with self.assertRaises(ValueError):
                w.read_public('https://example.com/')
            self.assertEqual(connect.call_count, 1)
        listing = ''.join('<a href="/jobs/' + str(i) + '">Job</a>' for i in range(10))
        text = '<script type="application/ld+json">' + json.dumps(posting()) + '</script>'
        with patch.object(w, 'read_public', side_effect=[listing, text, text]) as read, patch.object(w.time, 'sleep'):
            jobs, _ = w.fetch_custom(w.custom_spec('Name', 'https://example.com/search'), limit=2)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(read.call_count, 3)

    def test_structured_graph_locations_and_expiry(self):
        page = w.Page('<script type="application/ld+json">' + json.dumps({'@graph': [posting()]}) + '</script>')
        job = w.normalize(next(w.postings(page.structured)), 'https://nextleveljobs.eu/companies/a/jobs/1', 'nextleveljobs')
        self.assertEqual(job['location'], 'Berlin, DE')
        self.assertEqual(job['company'], 'Example')
        self.assertNotIn('<p>', job['description'])
        self.assertIsNone(w.normalize(posting(validThrough='2000-01-01'), job['url'], 'nextleveljobs'))
        with self.assertRaises(ValueError):
            w.normalize(posting(description='Teaser'), job['url'], 'nextleveljobs')

    def test_no_external_fetches_or_duplicate_details(self):
        listing = '<a href="/companies/a/jobs/1">One</a>' * 2
        listing += '<a href="https://127.0.0.1/companies/a/jobs/2">Unsafe</a>'
        detail = '<script type="application/ld+json">' + json.dumps(posting()) + '</script>'
        with patch.object(w, 'read', side_effect=[listing, detail]) as read, patch.object(w.time, 'sleep'):
            jobs, warnings = w.fetch('nextleveljobs')
        self.assertEqual(len(jobs), 1)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(warnings, [])
        for url in ('http://nextleveljobs.eu/x', 'https://nextleveljobs.eu:443/x', 'https://user@nextleveljobs.eu/x', '//127.0.0.1/x'):
            with self.assertRaises(ValueError):
                w.safe_url(url, w.SITES['nextleveljobs']['url'])

    def test_feed_and_cache(self):
        feed = '<rss><channel><item><title>Engineer @ Example [60.000 - 80.000 €]</title><link>https://germantechjobs.de/jobs/example?utm_source=rss</link><description>' + 'Build reliable services. ' * 12 + '</description></item></channel></rss>'
        with patch.object(w, 'read', return_value=feed):
            jobs, warnings = w.fetch('germantechjobs')
        self.assertEqual(jobs[0]['company'], 'Example')
        self.assertEqual(jobs[0]['title'], 'Engineer')
        self.assertEqual(jobs[0]['url'], 'https://germantechjobs.de/jobs/example')
        with tempfile.TemporaryDirectory() as directory:
            text = '<script type="application/ld+json">' + json.dumps(posting()) + '</script>'
            with patch.object(w, 'read', return_value=text) as read:
                first = w.detail('https://berlinstartupjobs.com/engineering/example/', 'berlinstartupjobs', directory)
                second = w.detail(first['url'], 'berlinstartupjobs', directory)
            self.assertEqual(first, second)
            self.assertEqual(read.call_count, 1)

    def test_site_failure_isolated_in_pipeline(self):
        import jobpipe as jp
        with patch.dict(jp.CFG, boards={}, website_sources=['devjobs', 'germantechjobs']), patch.object(w, 'fetch', side_effect=[ValueError('Verification required'), ([{'id': 'ok'}], [])]):
            self.assertEqual(jp.fetch_boards(), [{'id': 'ok'}])

    def test_request_challenge_and_size_limits(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status_code = 403
        with patch.object(w.requests, 'get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'restricted'):
                w.read('https://en.devjobs.de/jobs/search')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        response.status_code = 200
        response.iter_content.return_value = [b'<script>window._cf_chl_opt={}</script>']
        with patch.object(w.requests, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, 'verification'):
                w.read('https://en.devjobs.de/jobs/search')

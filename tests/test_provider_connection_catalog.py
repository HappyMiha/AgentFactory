from datetime import datetime, timezone
import unittest
from agent_factory.provider_connection_catalog import connection_catalog


class ConnectionCatalogTests(unittest.TestCase):
    def test_api_keys_and_official_cli_login_are_separate_from_chat(self):
        result = connection_catalog(now=datetime(2026,9,6,tzinfo=timezone.utc))
        products = {item['id']: item for item in result['products']}
        self.assertEqual({p['provider'] for p in products.values() if p['key_storage_option']}, {'openai','anthropic'})
        for key in ('chatgpt','claude-chat','codex-cli','claude-code','other'):
            self.assertFalse(products[key]['key_storage_option'])
            self.assertIsNone(products[key]['provider'])
        self.assertEqual(products['codex-cli']['flow'], 'official_cli_login')
        self.assertFalse(result['execution_ready'])
        self.assertEqual(result['qualified_capabilities'], [])
        self.assertEqual(set(result['connection_checks'].values()), {'not_run'})

    def test_expired_or_future_catalogue_cannot_offer_key_selection(self):
        for instant in (datetime(2026,9,5,tzinfo=timezone.utc), datetime(2026,10,6,tzinfo=timezone.utc)):
            result = connection_catalog(now=instant)
            self.assertFalse(result['current'])
            self.assertFalse(any(p['key_storage_option'] for p in result['products']))
        with self.assertRaises(ValueError): connection_catalog(now=datetime(2026,9,6))

    def test_copy_does_not_mutate_catalogue_or_include_executable_login(self):
        now=datetime(2026,9,6,tzinfo=timezone.utc)
        result=connection_catalog(now=now)
        result['products'][0]['steps'].clear()
        another=connection_catalog(now=now)
        self.assertTrue(another['products'][0]['steps'])
        self.assertTrue(all(not any(k in p for k in ('executor','callback','token','secret')) for p in another['products']))

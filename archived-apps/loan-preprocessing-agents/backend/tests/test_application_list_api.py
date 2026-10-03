"""Owner isolation, global sorting, page boundaries and query validation."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
import test_application_detail_api as detail_tests
import main
import models
import security


class ApplicationListApiTests(unittest.TestCase):
    tearDown = detail_tests.ApplicationDetailApiTests.tearDown
    def setUp(self):
        detail_tests.ApplicationDetailApiTests.setUp(self)
        with self.session_factory() as session:
            session.query(models.Application).update({models.Application.owner_id: 2})
            for n in range(1, 122):
                session.add(models.Application(
                    id=n+10, owner_id=1, app_id_str=f'APP-{n:03d}',
                    applicant_name=['alice', 'Bob', 'ALICE'][n % 3],
                    loan_type=['Home', 'auto'][n % 2], amount=Decimal(n*13 % 127),
                    status='processing' if n == 1 else 'Passed',
                    submitted_date=date(2026, 1, 1)+timedelta(days=n % 15),
                    validation_comments=[None, '', '  ', 'Alpha', 'beta'][n % 5]))
            session.commit()

    def collection(self, **params):
        response = self.client.get('/applications', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pages_and_owner_metadata(self):
        pages = [self.collection(page=n) for n in (1, 2, 3)]
        self.assertEqual([len(p['items']) for p in pages], [50, 50, 21])
        self.assertEqual(len({r['id'] for p in pages for r in p['items']}), 121)
        for p in pages:
            self.assertEqual((p['total'], p['total_pages'], p['page_size']), (121, 3, 50))
            self.assertTrue(p['has_active_applications'])
        self.assertEqual(self.collection(page=99)['page'], 3)
        self.assertNotIn('processing', [r['status'] for r in pages[0]['items']])

    def test_all_sort_fields(self):
        with self.session_factory() as session:
            records = list(session.query(models.Application).filter_by(owner_id=1))
            for field in ['app_id_str', 'applicant_name', 'loan_type', 'amount', 'status',
                          'validation_comments', 'submitted_date']:
                for direction in ['asc', 'desc']:
                    with self.subTest(field=field, direction=direction):
                        def value(row):
                            v = getattr(row, field)
                            return v.strip().lower() if isinstance(v, str) else v
                        nonblank = [r for r in records if value(r) not in (None, '')]
                        blank = [r for r in records if value(r) in (None, '')]
                        expected = sorted(nonblank, key=lambda r: -r.id)
                        expected.sort(key=value, reverse=direction == 'desc')
                        expected += sorted(blank, key=lambda r: -r.id)
                        actual = [r for p in (1, 2, 3) for r in self.collection(
                            page=p, sort_by=field, sort_direction=direction)['items']]
                        self.assertEqual([r['id'] for r in actual], [r.id for r in expected])

    def test_empty_and_activity_isolation(self):
        main.app.dependency_overrides[security.get_current_user] = lambda: SimpleNamespace(id=3)
        data = self.collection(page=10)
        self.assertEqual(data['items'], [])
        self.assertEqual((data['total'], data['total_pages'], data['page']), (0, 0, 1))
        self.assertFalse(data['has_active_applications'])
        main.app.dependency_overrides[security.get_current_user] = lambda: SimpleNamespace(id=2)
        self.assertFalse(self.collection()['has_active_applications'])

    def test_invalid_queries_and_authentication(self):
        for params in [{'page': 0}, {'page_size': 0}, {'page_size': 101},
                       {'sort_by': 'owner_id'}, {'sort_by': 'id;DROP TABLE applications'},
                       {'sort_direction': 'sideways'}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get('/applications', params=params).status_code, 422)
        del main.app.dependency_overrides[security.get_current_user]
        self.assertEqual(self.client.get('/applications').status_code, 401)

    def test_legacy_collection(self):
        response = self.client.get('/list_applications')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 121)

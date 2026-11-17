import unittest
from followup.app import Application
from followup.store import Store
from followup.eligibility import eligible, contactable
from followup.questionnaires import monthly_observed, save_response
from followup.visits import assign_contact, finish_contact


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        Application(self.store).seed()

    def tearDown(self):
        self.store.close()

    def test_exit_date(self):
        self.assertNotIn('r3', [row['id'] for row in eligible(self.store, '2026-10-15')])

    def test_consent_and_recent_contact(self):
        self.assertEqual([row['id'] for row in contactable(self.store, '2026-11-01')], ['r1'])

    def test_interval_boundary(self):
        self.assertIn('r2', [row['id'] for row in contactable(self.store, '2026-11-05')])

    def test_partial_response_mean(self):
        self.assertEqual(monthly_observed(self.store, '2026-10')['observed_mean'], 4.5)

    def test_no_response_is_not_zero(self):
        self.assertIsNone(monthly_observed(self.store, '2027-01')['observed_mean'])

    def test_invalid_item(self):
        row = dict(self.store.get('responses', 'q1'), items=[6])
        with self.assertRaises(ValueError):
            save_response(self.store, row)

    def test_interviewer_scope(self):
        with self.assertRaises(ValueError):
            assign_contact(self.store, 'r2', 'i1', '2026-11-10')

    def test_only_one_open_job(self):
        assign_contact(self.store, 'r1', 'i1', '2026-11-01')
        with self.assertRaises(ValueError):
            assign_contact(self.store, 'r1', 'i2', '2026-11-02')

    def test_refusal_changes_contact_eligibility(self):
        job = assign_contact(self.store, 'r1', 'i1', '2026-11-01')
        finish_contact(self.store, job['id'], 'refused')
        self.assertNotIn('r1', [row['id'] for row in contactable(self.store, '2026-12-01')])

    def test_contact_result_cannot_be_repeated(self):
        job = assign_contact(self.store, 'r1', 'i1', '2026-11-01')
        finish_contact(self.store, job['id'], 'unreachable')
        with self.assertRaises(ValueError):
            finish_contact(self.store, job['id'], 'responded')

import unittest
from followup.app import Application
from followup.store import Store
from followup.eligibility import contactable
from followup.longitudinal import decompose, longitudinal_report, month_window, monthly_snapshot, sensitivity
from followup.planning import plan_followups
from followup.visits import assign_contact, finish_contact


class LongitudinalTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        Application(self.store).seed()

    def tearDown(self):
        self.store.close()

    def test_cohort_comes_from_eligibility_not_scores(self):
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['cohort']['total'], 3)
        self.assertEqual(snap['cohort']['members'], ['r1', 'r2', 'r4'])
        self.assertEqual(snap['observed']['people'], 0)
        self.assertIsNone(snap['observed']['mean'])
        self.assertEqual(snap['missing']['total'], 3)
        self.assertEqual(snap['missing']['reasons']['no_consent'], ['r4'])
        self.assertEqual(snap['coverage'], 0)

    def test_exit_reasons_and_history_kept(self):
        october = monthly_snapshot(self.store, '2026-10')
        self.assertEqual(october['cohort']['exited'], ['r3'])
        self.assertEqual(october['cohort']['exit_reasons'], {'transfer': ['r3']})
        self.assertNotIn('r5', october['cohort']['members'])
        september = monthly_snapshot(self.store, '2026-09')
        self.assertEqual(september['cohort']['exit_reasons'], {'deceased': ['r5']})
        august = monthly_snapshot(self.store, '2026-08')
        self.assertEqual(august['observed']['people'], 1)
        self.assertEqual(august['observed']['mean'], 3.0)

    def test_partial_items_still_valid(self):
        snap = monthly_snapshot(self.store, '2026-10')
        self.assertEqual(snap['observed']['people'], 1)
        self.assertEqual(snap['observed']['partial_responses'], 1)
        self.assertAlmostEqual(snap['observed']['mean'], 4.5)
        self.assertAlmostEqual(snap['observed']['answered_share'], 2 / 3, places=3)
        self.assertEqual(snap['observed']['by_mode']['family']['people'], 1)

    def test_absence_and_missing_reasons(self):
        snap = monthly_snapshot(self.store, '2026-10')
        self.assertEqual(snap['cohort']['absent'], ['r2'])
        self.assertEqual(snap['missing']['reasons']['absent_hospital'], ['r2'])
        self.assertEqual(snap['missing']['reasons']['not_attempted'], ['r3'])
        self.assertEqual(snap['missing']['reasons']['no_consent'], ['r4'])

    def test_mode_switch_not_pooled(self):
        change = decompose(self.store, '2026-09', '2026-10')
        self.assertTrue(change['available'])
        self.assertEqual(change['groups']['stayers_same_mode']['residents'], [])
        self.assertEqual(change['groups']['mode_switched']['residents'], ['r1'])
        self.assertEqual(change['groups']['mode_switched']['detail'], [{'resident': 'r1', 'from_mode': 'self', 'to_mode': 'family'}])
        self.assertEqual(change['groups']['leavers']['residents'], ['r3'])
        self.assertEqual(change['components']['within_same_mode'], 0)
        self.assertEqual(change['components']['mode_switched'], 1.0)

    def test_components_sum_to_observed_change(self):
        change = decompose(self.store, '2026-09', '2026-10')
        observed = change['observed']['change']
        self.assertAlmostEqual(sum(change['components'].values()), observed, places=3)
        self.assertAlmostEqual(observed, 4.5 - (3.5 + 7 / 3) / 2, places=3)
        self.assertAlmostEqual(change['components_sum'], observed, places=3)

    def test_unidentified_part_is_stated(self):
        change = decompose(self.store, '2026-09', '2026-10')
        self.assertIn('无法由现有资料识别', change['unidentified'])
        self.assertEqual(change['cohort']['missing_from'], 3)
        self.assertEqual(change['cohort']['missing_to'], 3)

    def test_sensitivity_bounds_and_sign(self):
        result = sensitivity(self.store, '2026-09', '2026-10')
        self.assertTrue(result['available'])
        self.assertFalse(result['bounds']['sign_identified'])
        self.assertLess(result['bounds']['min_change'], 0)
        self.assertGreater(result['bounds']['max_change'], 0)
        self.assertEqual(set(result['scenarios']), {'floor', 'ceiling', 'observed', 'last', 'most_favorable', 'least_favorable'})
        self.assertIn('无法判定', result['note'])

    def test_sign_identified_only_when_bounds_agree(self):
        store = Store(':memory:')
        try:
            residents = [{'id': f'p{k}', 'site': 'east', 'entered': '2026-01-01', 'left': None, 'consent': True, 'contact': f't{k}', 'contact_gap_days': 7} for k in range(6)]
            store.put_many('residents', residents)
            responses = []
            for k in range(5):
                responses.append({'id': f'a{k}', 'resident': f'p{k}', 'date': '2026-09-10', 'respondent': 'self', 'items': [1, 1, 1]})
                responses.append({'id': f'b{k}', 'resident': f'p{k}', 'date': '2026-10-10', 'respondent': 'self', 'items': [5, 5, 5]})
            store.put_many('responses', responses)
            result = sensitivity(store, '2026-09', '2026-10')
            self.assertTrue(result['bounds']['sign_identified'])
            self.assertGreater(result['bounds']['min_change'], 0)
            change = decompose(store, '2026-09', '2026-10')
            self.assertAlmostEqual(change['components']['within_same_mode'], 4.0)
        finally:
            store.close()

    def test_unreachable_recent_and_awaiting_record(self):
        self.store.put('contacts', {'id': 'c1', 'resident': 'r1', 'date': '2026-11-25', 'result': 'unreachable'})
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['missing']['reasons']['unreachable_recent'], ['r1'])
        self.store.put('contacts', {'id': 'c2', 'resident': 'r1', 'date': '2026-11-28', 'result': 'responded'})
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['missing']['reasons']['awaiting_record'], ['r1'])

    def test_report_includes_note_and_change(self):
        report = longitudinal_report(self.store, '2026-10', 2)
        self.assertIn('服务质量', report['note'])
        self.assertEqual([row['month'] for row in report['months']], ['2026-09', '2026-10'])
        self.assertTrue(report['change']['available'])
        self.assertIn('sensitivity', report['change'])

    def test_month_window_validation(self):
        self.assertEqual(month_window('2026-01', 2), ['2025-12', '2026-01'])
        with self.assertRaises(ValueError):
            month_window('2026-13', 2)
        with self.assertRaises(ValueError):
            month_window('2026-11', 0)
        with self.assertRaises(ValueError):
            decompose(self.store, '2026-10', '2026-09')


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        Application(self.store).seed()

    def tearDown(self):
        self.store.close()

    def test_plan_prioritizes_information_gaps(self):
        plan = plan_followups(self.store, '2026-11-10', 5)
        self.assertEqual([entry['resident'] for entry in plan['entries']], ['r2', 'r1'])
        by_resident = {entry['resident']: entry for entry in plan['entries']}
        self.assertEqual(by_resident['r2']['interviewer'], 'i2')
        self.assertEqual(by_resident['r1']['interviewer'], 'i1')
        self.assertGreater(by_resident['r2']['value_score'], by_resident['r1']['value_score'])
        self.assertTrue(all(entry['reasons'] for entry in plan['entries']))
        self.assertEqual(by_resident['r2']['feasibility']['interviewers'], ['i2'])
        self.assertEqual(plan['unfilled'], 3)

    def test_plan_creates_open_jobs_and_blocks_duplicates(self):
        plan = plan_followups(self.store, '2026-11-10', 1)
        job = self.store.get('jobs', 'r2:2026-11-10')
        self.assertEqual(job['status'], 'open')
        self.assertEqual(job['plan'], plan['id'])
        with self.assertRaises(ValueError):
            assign_contact(self.store, 'r2', 'i2', '2026-11-10')

    def test_second_plan_skips_residents_with_open_jobs(self):
        plan_followups(self.store, '2026-11-10', 5)
        again = plan_followups(self.store, '2026-11-10', 5)
        self.assertEqual(again['entries'], [])
        self.assertEqual(again['excluded']['open_job'], 2)

    def test_site_scope_and_validation(self):
        east = plan_followups(self.store, '2026-11-10', 5, site='east')
        self.assertEqual([entry['resident'] for entry in east['entries']], ['r1'])
        with self.assertRaises(ValueError):
            plan_followups(self.store, '2026-11-10', 0)
        with self.assertRaises(ValueError):
            plan_followups(self.store, '2026-11-10', 2, site='nowhere')
        with self.assertRaises(ValueError):
            plan_followups(self.store, 'not-a-date', 2)

    def test_no_covering_interviewer_is_explained(self):
        self.store.put('residents', {'id': 'r9', 'site': 'north', 'entered': '2026-01-01', 'left': None, 'consent': True, 'contact': 'token9', 'contact_gap_days': 7})
        plan = plan_followups(self.store, '2026-11-10', 5)
        skipped = {row['resident']: row for row in plan['skipped']}
        self.assertIn('r9', skipped)
        self.assertTrue(any('无访员覆盖' in reason for reason in skipped['r9']['reasons']))

    def test_absent_resident_not_scheduled(self):
        self.store.put('absences', {'id': 'a9', 'resident': 'r1', 'start': '2026-11-05', 'end': '2026-11-15', 'reason': 'hospital'})
        plan = plan_followups(self.store, '2026-11-10', 5)
        self.assertNotIn('r1', [entry['resident'] for entry in plan['entries']])
        self.assertIn('r1', {row['resident'] for row in plan['skipped']})

    def test_reasons_frozen_after_contact_result(self):
        plan = plan_followups(self.store, '2026-11-10', 5)
        before = self.store.get('plans', plan['id'])
        finish_contact(self.store, 'r2:2026-11-10', 'refused')
        after = self.store.get('plans', plan['id'])
        self.assertEqual(before, after)
        self.assertNotIn('r2', [row['id'] for row in contactable(self.store, '2026-12-01')])
        followup = plan_followups(self.store, '2026-12-05', 5)
        self.assertNotIn('r2', [entry['resident'] for entry in followup['entries']])
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['missing']['reasons']['refused'], ['r2'])

    def test_invalid_contact_blocks_until_token_corrected(self):
        job = assign_contact(self.store, 'r1', 'i1', '2026-11-01')
        finish_contact(self.store, job['id'], 'invalid')
        self.assertNotIn('r1', [row['id'] for row in contactable(self.store, '2026-11-10')])
        contact = self.store.get('contacts', job['id'])
        self.assertEqual(contact['contact'], 'token1')
        resident = self.store.get('residents', 'r1')
        revision = self.store.revision('residents', 'r1')
        self.store.put('residents', dict(resident, contact='token1-new'), expected=revision)
        self.assertIn('r1', [row['id'] for row in contactable(self.store, '2026-11-10')])

    def test_responded_result_becomes_analysis_evidence(self):
        job = assign_contact(self.store, 'r1', 'i1', '2026-11-02')
        finish_contact(self.store, job['id'], 'responded')
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['missing']['reasons']['awaiting_record'], ['r1'])
        self.store.put('responses', {'id': 'q9', 'resident': 'r1', 'date': '2026-11-02', 'respondent': 'self', 'items': [5, 5, 5]})
        snap = monthly_snapshot(self.store, '2026-11')
        self.assertEqual(snap['observed']['people'], 1)
        self.assertNotIn('r1', snap['missing']['reasons'].get('awaiting_record', []))

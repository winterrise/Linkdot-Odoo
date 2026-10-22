from datetime import date

from freezegun import freeze_time

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestLinkdotHealthCheck(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = new_test_user(
            cls.env, login='hc_officer', groups='base.group_user,linkdot_health_check.group_health_check_officer')
        cls.staff_user = new_test_user(cls.env, login='hc_staff', groups='base.group_user')
        cls.other_user = new_test_user(cls.env, login='hc_other', groups='base.group_user')
        Employee = cls.env['hr.employee']
        cls.staff = Employee.create({
            'name': 'Staff', 'user_id': cls.staff_user.id, 'birthday': date(1990, 6, 1)})
        cls.other = Employee.create({
            'name': 'Other', 'user_id': cls.other_user.id, 'birthday': date(1960, 1, 1)})
        cls.Check = cls.env['linkdot.health.check']

    def _done_check(self, employee, check_date, check_type='general', **vals):
        return self.Check.create(dict(
            employee_id=employee.id, check_type=check_type, check_date=check_date, state='done', **vals))

    def test_interval_by_age(self):
        Employee = self.env['hr.employee']
        self.assertEqual(Employee._get_general_check_interval(30), 5)
        self.assertEqual(Employee._get_general_check_interval(40), 3)
        self.assertEqual(Employee._get_general_check_interval(64), 3)
        self.assertEqual(Employee._get_general_check_interval(65), 1)

    def test_next_date_under_40(self):
        self._done_check(self.staff, date(2020, 3, 1))
        self.assertEqual(self.staff.last_health_check_date, date(2020, 3, 1))
        # 2025-03-01 時 34 歲，每 5 年
        self.assertEqual(self.staff.next_health_check_date, date(2025, 3, 1))

    def test_next_date_crossing_40(self):
        # 2028-03-01 檢查時 37 歲；2031-03-01 時 40 歲，週期縮短為 3 年
        self._done_check(self.staff, date(2028, 3, 1))
        self.assertEqual(self.staff.next_health_check_date, date(2031, 3, 1))

    def test_next_date_over_65(self):
        self._done_check(self.other, date(2026, 5, 1))
        self.assertEqual(self.other.next_health_check_date, date(2027, 5, 1))

    def test_pre_employment_resets_cycle_special_does_not(self):
        self._done_check(self.staff, date(2024, 1, 10), check_type='pre_employment')
        self._done_check(self.staff, date(2025, 1, 10), check_type='special', special_hazard='Noise')
        self.assertEqual(self.staff.last_health_check_date, date(2024, 1, 10))

    def test_special_requires_hazard(self):
        with self.assertRaises(ValidationError):
            self.Check.create({'employee_id': self.staff.id, 'check_type': 'special'})

    def test_done_sets_date_and_follow_up_activity(self):
        self.env.company.health_check_officer_id = self.officer
        check = self.Check.create({
            'employee_id': self.staff.id, 'scheduled_date': date(2026, 4, 1), 'result': 'abnormal'})
        self.assertTrue(check.follow_up_required)
        check.action_schedule()
        check.action_done()
        self.assertEqual(check.state, 'done')
        self.assertEqual(check.check_date, date(2026, 4, 1))
        activity = check.activity_ids
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.user_id, self.officer)
        self.assertEqual(activity.activity_type_id,
                         self.env.ref('linkdot_health_check.mail_activity_type_follow_up'))

    def test_management_level_requires_follow_up(self):
        check = self.Check.create({
            'employee_id': self.staff.id, 'check_type': 'special', 'special_hazard': 'Lead',
            'management_level': '1'})
        self.assertFalse(check.follow_up_required)
        check.management_level = '3'
        self.assertTrue(check.follow_up_required)

    def test_employee_sees_only_own_records(self):
        own = self._done_check(self.staff, date(2025, 1, 1))
        other = self._done_check(self.other, date(2025, 1, 1))
        visible = self.Check.with_user(self.staff_user).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)
        with self.assertRaises(AccessError):
            own.with_user(self.staff_user).write({'result': 'normal'})
        with self.assertRaises(AccessError):
            other.with_user(self.staff_user).read(['result'])

    def test_officer_sees_all(self):
        checks = self._done_check(self.staff, date(2025, 1, 1)) | self._done_check(self.other, date(2025, 1, 1))
        self.assertEqual(self.Check.with_user(self.officer).search([('id', 'in', checks.ids)]), checks)

    def test_done_record_retained(self):
        check = self._done_check(self.staff, date(2025, 1, 1))
        with self.assertRaises(UserError):
            check.with_user(self.officer).unlink()
        draft = self.Check.create({'employee_id': self.staff.id})
        draft.with_user(self.officer).unlink()

    @freeze_time('2026-10-22')
    def test_cron_creates_due_checks_once(self):
        self.env.company.health_check_officer_id = self.officer
        self._done_check(self.staff, date(2021, 11, 1))   # 下次 2026-11-01，60 天內到期
        self._done_check(self.other, date(2026, 5, 1))    # 下次 2027-05-01，還早
        Employee = self.env['hr.employee']
        Employee._cron_create_due_health_checks()
        open_checks = self.Check.search([('state', '=', 'draft'), ('employee_id', 'in', (self.staff | self.other).ids)])
        self.assertEqual(open_checks.employee_id, self.staff)
        self.assertEqual(open_checks.scheduled_date, date(2026, 11, 1))
        self.assertEqual(open_checks.activity_ids.user_id, self.officer)
        self.assertEqual(self.staff.health_check_status, 'due_soon')
        self.assertEqual(self.other.health_check_status, 'ok')
        # 再跑一次不會重複建立
        Employee._cron_create_due_health_checks()
        self.assertEqual(self.Check.search_count([('state', '=', 'draft'), ('employee_id', '=', self.staff.id)]), 1)

    def test_plan_wizard_reuses_open_check(self):
        existing = self.Check.create({'employee_id': self.staff.id})
        wizard = self.env['linkdot.health.check.plan.wizard'].with_user(self.officer).with_context(
            active_model='hr.employee', active_ids=(self.staff | self.other).ids,
        ).create({'scheduled_date': date(2026, 12, 1)})
        self.assertEqual(wizard.employee_ids, self.staff | self.other)
        action = wizard.action_schedule()
        checks = self.Check.browse(action['domain'][0][2])
        self.assertEqual(len(checks), 2)
        self.assertIn(existing, checks)
        self.assertEqual(set(checks.mapped('state')), {'scheduled'})

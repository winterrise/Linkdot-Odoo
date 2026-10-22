from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

from .linkdot_health_check import CYCLE_RESETTING_TYPES, OFFICER_GROUP, SCHEDULE_ACTIVITY

DEFAULT_REMINDER_DAYS = 60


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    health_check_ids = fields.One2many(
        'linkdot.health.check', 'employee_id', string='Health Checks', groups=OFFICER_GROUP)
    health_check_count = fields.Integer(
        compute='_compute_health_check_count', groups=OFFICER_GROUP)
    # 員工資料上的非公開欄位要限定 HR 權限（hr 模組慣例），否則非 HR 使用者讀員工時會連帶讀到而被擋；
    # 健康管理人員改由 linkdot.health.check.employee.status 讀這兩個日期。
    last_health_check_date = fields.Date(
        string='Last General Health Check', compute='_compute_health_check_dates',
        store=True, groups='hr.group_hr_user')
    next_health_check_date = fields.Date(
        string='Next General Health Check Due', compute='_compute_health_check_dates',
        store=True, groups='hr.group_hr_user')

    @api.depends('health_check_ids')
    def _compute_health_check_count(self):
        counts = dict(self.env['linkdot.health.check']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for employee in self:
            employee.health_check_count = counts.get(employee, 0)

    @api.depends('birthday', 'health_check_ids.state', 'health_check_ids.check_date',
                 'health_check_ids.check_type')
    def _compute_health_check_dates(self):
        for employee in self:
            dates = employee.health_check_ids.filtered(
                lambda c: c.state == 'done' and c.check_type in CYCLE_RESETTING_TYPES and c.check_date
            ).mapped('check_date')
            last = max(dates) if dates else False
            employee.last_health_check_date = last
            employee.next_health_check_date = last and employee._get_next_health_check_date(last)

    @api.model
    def _get_general_check_interval(self, age):
        """勞工健康保護規則第17條：65歲以上每年、40-64歲每3年、未滿40歲每5年。"""
        if age >= 65:
            return 1
        if age >= 40:
            return 3
        return 5

    def _get_next_health_check_date(self, last_date):
        """Earliest date after last_date whose elapsed years reach the interval for the age on that date."""
        self.ensure_one()
        for years in range(1, 6):
            candidate = last_date + relativedelta(years=years)
            age = relativedelta(candidate, self.birthday).years if self.birthday else 0
            if years >= self._get_general_check_interval(age):
                return candidate
        return last_date + relativedelta(years=5)


    @api.model
    def _get_health_check_reminder_days(self):
        value = self.env['ir.config_parameter'].sudo().get_param('linkdot_health_check.reminder_days')
        try:
            return int(value) if value else DEFAULT_REMINDER_DAYS
        except ValueError:
            return DEFAULT_REMINDER_DAYS

    def action_open_health_checks(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('linkdot_health_check.linkdot_health_check_action')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    @api.model
    def _cron_create_due_health_checks(self):
        """為即將到期或從未健檢的在職員工建立「待安排」的一般健康檢查，並提醒健康管理人員。"""
        today = fields.Date.context_today(self)
        limit_date = today + timedelta(days=self._get_health_check_reminder_days())
        employees = self.search([
            '|', ('next_health_check_date', '=', False), ('next_health_check_date', '<=', limit_date),
        ])
        open_checks = self.env['linkdot.health.check'].search([
            ('employee_id', 'in', employees.ids),
            ('check_type', 'in', CYCLE_RESETTING_TYPES),
            ('state', 'in', ('draft', 'scheduled', 'reported')),
        ])
        employees -= open_checks.employee_id
        if not employees:
            return
        checks = self.env['linkdot.health.check'].create([{
            'employee_id': employee.id,
            'check_type': 'general',
            'scheduled_date': employee.next_health_check_date,
        } for employee in employees])
        for check in checks:
            check._schedule_reminders(
                SCHEDULE_ACTIVITY, max(check.scheduled_date or today, today),
                note=_("General health check due for %s.", check.employee_id.name))

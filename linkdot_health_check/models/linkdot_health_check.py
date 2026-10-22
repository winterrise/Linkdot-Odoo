from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# 勞工健康保護規則：新進體格檢查、定期一般健康檢查、特殊健康檢查
CHECK_TYPES = [
    ('pre_employment', 'Pre-employment Physical Examination'),
    ('general', 'General Health Check'),
    ('special', 'Special Health Check'),
    ('other', 'Other'),
]

# 這兩類檢查會重新起算下一次一般健康檢查的週期
CYCLE_RESETTING_TYPES = ('pre_employment', 'general')

OFFICER_GROUP = 'linkdot_health_check.group_health_check_officer'
MANAGER_GROUP = 'linkdot_health_check.group_health_check_manager'
SCHEDULE_ACTIVITY = 'linkdot_health_check.mail_activity_type_schedule'
FOLLOW_UP_ACTIVITY = 'linkdot_health_check.mail_activity_type_follow_up'


def _provider_domain():
    """醫療機構只列出同公司（或共用）且能做該類檢查的機構；前端以 check_type、company_id 求值。"""
    base = "('company_id', 'in', [False, company_id])"
    expr = "[%s]" % base
    for check_type in ('pre_employment', 'general', 'special'):
        expr = "[%s, ('offers_%s', '=', True)] if check_type == '%s' else %s" % (
            base, check_type, check_type, expr)
    return expr


PROVIDER_DOMAIN = _provider_domain()


class LinkdotHealthCheck(models.Model):
    _name = 'linkdot.health.check'
    _description = 'Employee Health Check'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'check_date desc, scheduled_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, index=True, tracking=True,
        domain="[('company_id', 'in', allowed_company_ids)]")
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one(
        'hr.department', related='employee_id.department_id', store=True)
    check_type = fields.Selection(
        CHECK_TYPES, string='Check Type', required=True, default='general', tracking=True)
    special_hazard = fields.Char(
        string='Special Hazardous Work',
        help="Hazardous work item that requires this special health check, e.g. noise, lead, night shift.")
    state = fields.Selection([
        ('draft', 'To Schedule'),
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', required=True, default='draft', tracking=True, copy=False)
    provider_id = fields.Many2one(
        'linkdot.health.check.provider', string='Medical Institution', tracking=True,
        domain=PROVIDER_DOMAIN, ondelete='restrict',
        help="Medical institution that performs the check. Administrators maintain the list "
             "in Health Checks > Configuration > Medical Institutions.")
    scheduled_date = fields.Date(string='Scheduled Date', tracking=True)
    check_date = fields.Date(string='Check Date', tracking=True, copy=False)

    result = fields.Selection([
        ('normal', 'Normal'),
        ('abnormal', 'Abnormal'),
    ], string='Result', tracking=True, copy=False)
    management_level = fields.Selection([
        ('1', 'Level 1'),
        ('2', 'Level 2'),
        ('3', 'Level 3'),
        ('4', 'Level 4'),
    ], string='Health Management Level', tracking=True, copy=False,
        help="Health management level of a special health check (Labor Health Protection Rules, Article 21).")
    result_summary = fields.Text(string='Result Summary', copy=False)
    report_attachment_ids = fields.Many2many(
        'ir.attachment', string='Reports', copy=False,
        help="Scanned or electronic health check reports.")

    follow_up_required = fields.Boolean(
        string='Follow-up Required', compute='_compute_follow_up_required',
        store=True, readonly=False, tracking=True, copy=False)
    follow_up_date = fields.Date(string='Follow-up Date', copy=False)
    follow_up_done = fields.Boolean(string='Follow-up Done', tracking=True, copy=False)
    follow_up_note = fields.Text(string='Follow-up Notes', copy=False)

    currency_id = fields.Many2one(related='company_id.currency_id')
    cost = fields.Monetary(string='Cost')
    paid_by = fields.Selection([
        ('company', 'Company'),
        ('employee', 'Employee'),
    ], string='Paid By', default='company')
    note = fields.Text(string='Notes')

    @api.depends('employee_id.name', 'check_type', 'check_date', 'scheduled_date')
    def _compute_name(self):
        type_labels = dict(self._fields['check_type']._description_selection(self.env))
        for check in self:
            date = check.check_date or check.scheduled_date
            parts = [check.employee_id.name or '', type_labels.get(check.check_type, '')]
            if date:
                parts.append(fields.Date.to_string(date))
            check.name = ' - '.join(p for p in parts if p)

    @api.depends('result', 'management_level')
    def _compute_follow_up_required(self):
        for check in self:
            check.follow_up_required = (
                check.result == 'abnormal'
                or check.management_level in ('2', '3', '4')
            )

    @api.constrains('check_type', 'special_hazard')
    def _check_special_hazard(self):
        for check in self:
            if check.check_type == 'special' and not check.special_hazard:
                raise ValidationError(_("A special health check must state its hazardous work item."))

    @api.constrains('state', 'check_date')
    def _check_done_has_date(self):
        for check in self:
            if check.state == 'done' and not check.check_date:
                raise ValidationError(_("A completed health check needs a check date."))

    def action_schedule(self):
        for check in self:
            if not check.scheduled_date:
                raise UserError(_("Please set the scheduled date of %s first.", check.display_name))
        self.write({'state': 'scheduled'})

    def action_done(self):
        for check in self:
            vals = {'state': 'done'}
            if not check.check_date:
                vals['check_date'] = check.scheduled_date or fields.Date.context_today(self)
            check.write(vals)

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def write(self, vals):
        res = super().write(vals)
        # 有人處理了，就把所有健康管理人員手上同一筆的提醒一起關掉
        if vals.get('state') in ('scheduled', 'done', 'cancelled'):
            self.activity_feedback([SCHEDULE_ACTIVITY])
        if {'state', 'result', 'management_level', 'follow_up_required', 'follow_up_date',
                'follow_up_done'} & set(vals):
            needs_follow_up = self.filtered(
                lambda c: c.state == 'done' and c.follow_up_required and not c.follow_up_done)
            (self - needs_follow_up).activity_feedback([FOLLOW_UP_ACTIVITY])
            needs_follow_up._schedule_follow_up_activities()
        return res

    @api.model
    def _get_reminder_users(self, company):
        """提醒對象＝該公司的健康管理人員（不含管理者）；沒有健康管理人員時改給管理者。"""
        officer_group = self.env.ref(OFFICER_GROUP)
        manager_group = self.env.ref(MANAGER_GROUP)

        def eligible(users):
            return users.filtered(lambda u: u.active and not u.share and company in u.company_ids
                                  and u != self.env.ref('base.user_root'))

        return eligible(officer_group.users - manager_group.users) or eligible(manager_group.users)

    def _schedule_reminders(self, activity_xmlid, date_deadline, note=None):
        """每位提醒對象各一筆待辦；已經有同類待辦的人不重複建立。"""
        activity_type = self.env.ref(activity_xmlid)
        for check in self:
            existing = check.activity_ids.filtered(lambda a: a.activity_type_id == activity_type).user_id
            for user in self._get_reminder_users(check.company_id) - existing:
                check.activity_schedule(
                    activity_type_id=activity_type.id, date_deadline=date_deadline,
                    note=note, user_id=user.id)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        # 健檢紀錄依法須保存（一般 7 年、特殊 30 年），只有管理者可以刪已完成的紀錄
        if self.filtered(lambda c: c.state == 'done') and not self.env.user.has_group(
                'linkdot_health_check.group_health_check_manager'):
            raise UserError(_("Completed health checks must be retained and can only be deleted by a Health Check Administrator."))

    def _schedule_follow_up_activities(self):
        for check in self:
            if not check.follow_up_required or check.follow_up_done:
                continue
            check._schedule_reminders(
                FOLLOW_UP_ACTIVITY, check.follow_up_date or fields.Date.context_today(check))

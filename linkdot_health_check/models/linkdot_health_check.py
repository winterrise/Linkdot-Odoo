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
        'res.partner', string='Medical Institution', tracking=True,
        help="Recognized medical institution that performs the check.")
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
        self._schedule_follow_up_activities()

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def write(self, vals):
        res = super().write(vals)
        if {'follow_up_required', 'follow_up_date'} & set(vals):
            self.filtered(lambda c: c.state == 'done')._schedule_follow_up_activities()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        # 健檢紀錄依法須保存（一般 7 年、特殊 30 年），只有管理者可以刪已完成的紀錄
        if self.filtered(lambda c: c.state == 'done') and not self.env.user.has_group(
                'linkdot_health_check.group_health_check_manager'):
            raise UserError(_("Completed health checks must be retained and can only be deleted by a Health Check Administrator."))

    def _schedule_follow_up_activities(self):
        activity_type = self.env.ref('linkdot_health_check.mail_activity_type_follow_up')
        for check in self:
            if not check.follow_up_required or check.follow_up_done:
                continue
            if check.activity_ids.filtered(lambda a: a.activity_type_id == activity_type):
                continue
            check.activity_schedule(
                activity_type_id=activity_type.id,
                date_deadline=check.follow_up_date or fields.Date.context_today(check),
                user_id=(check.company_id.health_check_officer_id or self.env.user).id,
            )

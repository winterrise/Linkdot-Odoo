from datetime import timedelta

from odoo import api, fields, models, tools


class LinkdotHealthCheckEmployeeStatus(models.Model):
    """員工健檢狀況（唯讀 SQL view）。

    沒有 HR 權限的使用者讀不到 hr.employee（Odoo 會改給 hr.employee.public，且生日屬 HR 欄位），
    所以健康管理人員改看這張只含必要欄位的 view：姓名、部門、職稱、生日、上次與下次健檢日。
    """
    _name = 'linkdot.health.check.employee.status'
    _description = 'Employee Health Check Status'
    _auto = False
    _order = 'next_health_check_date, name'
    # 讀 view 前先把這些員工欄位（含剛重算的健檢日期）寫進資料庫
    _depends = {
        'hr.employee': [
            'name', 'department_id', 'job_title', 'birthday', 'company_id', 'active',
            'last_health_check_date', 'next_health_check_date',
        ],
    }

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    name = fields.Char(string='Employee Name', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    job_title = fields.Char(string='Job Title', readonly=True)
    birthday = fields.Date(string='Date of Birth', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    last_health_check_date = fields.Date(string='Last General Health Check', readonly=True)
    next_health_check_date = fields.Date(string='Next General Health Check Due', readonly=True)
    health_check_status = fields.Selection([
        ('no_record', 'No Record'),
        ('ok', 'Up to Date'),
        ('due_soon', 'Due Soon'),
        ('overdue', 'Overdue'),
    ], string='Health Check Status', compute='_compute_health_check_status')
    health_check_count = fields.Integer(string='Checks', compute='_compute_health_check_count')

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT e.id,
                       e.id AS employee_id,
                       e.name,
                       e.department_id,
                       e.job_title,
                       e.birthday,
                       e.company_id,
                       e.last_health_check_date,
                       e.next_health_check_date
                  FROM hr_employee e
                 WHERE e.active
            )""" % self._table)

    @api.depends('next_health_check_date')
    def _compute_health_check_status(self):
        today = fields.Date.context_today(self)
        due_soon = today + timedelta(days=self.env['hr.employee']._get_health_check_reminder_days())
        for status in self:
            next_date = status.next_health_check_date
            if not next_date:
                status.health_check_status = 'no_record'
            elif next_date < today:
                status.health_check_status = 'overdue'
            elif next_date <= due_soon:
                status.health_check_status = 'due_soon'
            else:
                status.health_check_status = 'ok'

    def _compute_health_check_count(self):
        counts = dict(self.env['linkdot.health.check']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count']))
        for status in self:
            status.health_check_count = counts.get(status.employee_id, 0)

    def action_open_health_checks(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('linkdot_health_check.linkdot_health_check_action')
        action['domain'] = [('employee_id', '=', self.employee_id.id)]
        action['context'] = {'default_employee_id': self.employee_id.id}
        action['name'] = self.name
        return action

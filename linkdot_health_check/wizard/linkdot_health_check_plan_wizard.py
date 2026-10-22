from odoo import _, api, fields, models

from ..models.linkdot_health_check import CHECK_TYPES, PROVIDER_DOMAIN


class LinkdotHealthCheckPlanWizard(models.TransientModel):
    _name = 'linkdot.health.check.plan.wizard'
    _description = 'Schedule Health Checks'

    employee_ids = fields.Many2many('hr.employee', string='Employees', required=True)
    check_type = fields.Selection(CHECK_TYPES, string='Check Type', required=True, default='general')
    special_hazard = fields.Char(string='Special Hazardous Work')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    provider_id = fields.Many2one(
        'linkdot.health.check.provider', string='Medical Institution', domain=PROVIDER_DOMAIN)
    scheduled_date = fields.Date(string='Scheduled Date', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # 員工健檢狀況的 id 就是員工 id
        if 'employee_ids' in fields_list and self.env.context.get('active_model') in (
                'hr.employee', 'linkdot.health.check.employee.status'):
            res['employee_ids'] = [(6, 0, self.env.context.get('active_ids', []))]
        return res

    def action_schedule(self):
        self.ensure_one()
        Check = self.env['linkdot.health.check']
        # 同一位員工若已有同類型、尚未完成的健檢，就沿用那一筆，不重複建立
        existing = Check.search([
            ('employee_id', 'in', self.employee_ids.ids),
            ('check_type', '=', self.check_type),
            ('state', 'in', ('draft', 'scheduled')),
        ])
        vals = {
            'check_type': self.check_type,
            'special_hazard': self.special_hazard,
            'provider_id': self.provider_id.id,
            'scheduled_date': self.scheduled_date,
            'state': 'scheduled',
        }
        existing.write(vals)
        checks = existing | Check.create([
            dict(vals, employee_id=employee.id)
            for employee in self.employee_ids - existing.employee_id
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _("Scheduled Health Checks"),
            'res_model': 'linkdot.health.check',
            'view_mode': 'list,form',
            'domain': [('id', 'in', checks.ids)],
        }

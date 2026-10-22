from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    health_check_officer_id = fields.Many2one(
        'res.users', string='Health Check Officer',
        help="Receives reminders for due health checks and abnormal-result follow-ups.")

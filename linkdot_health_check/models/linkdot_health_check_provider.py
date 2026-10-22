from odoo import fields, models


class LinkdotHealthCheckProvider(models.Model):
    _name = 'linkdot.health.check.provider'
    _description = 'Health Check Medical Institution'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company,
        help="Leave empty to share this institution with all companies.")
    phone = fields.Char(string='Phone')
    address = fields.Char(string='Address')
    contact_name = fields.Char(string='Contact Person')
    # 勞動部認可的健檢項目不同：一般健檢與特殊健檢要分開認可
    offers_pre_employment = fields.Boolean(string='Pre-employment Physical', default=True)
    offers_general = fields.Boolean(string='General Health Check', default=True)
    offers_special = fields.Boolean(string='Special Health Check')
    note = fields.Text(string='Notes')

    _sql_constraints = [
        ('name_company_uniq', 'unique (name, company_id)',
         "A medical institution with this name already exists."),
    ]

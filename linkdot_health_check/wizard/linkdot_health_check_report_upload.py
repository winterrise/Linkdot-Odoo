import base64

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.linkdot_health_check import CHECK_TYPES, OFFICER_GROUP


class LinkdotHealthCheckReportUpload(models.TransientModel):
    _name = 'linkdot.health.check.report.upload'
    _description = 'Upload Health Check Report'

    check_id = fields.Many2one('linkdot.health.check', string='Health Check', readonly=True)
    is_officer = fields.Boolean(compute='_compute_is_officer')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id)
    check_type = fields.Selection(CHECK_TYPES, string='Check Type', required=True, default='general')
    special_hazard = fields.Char(string='Special Hazardous Work')
    check_date = fields.Date(string='Check Date', required=True)
    # 表單上必填；不設 required，上傳完才能清空（Odoo 不留副本）
    file = fields.Binary(string='Scanned Report', attachment=False)
    filename = fields.Char()

    def _compute_is_officer(self):
        self.is_officer = self.env.user.has_group(OFFICER_GROUP)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        check = self.env['linkdot.health.check'].browse(self.env.context.get('default_check_id'))
        if check:
            res.update({
                'employee_id': check.employee_id.id,
                'check_type': check.check_type,
                'special_hazard': check.special_hazard,
                'check_date': check.check_date or check.scheduled_date,
            })
        return res

    def _get_or_create_check(self):
        """回傳要掛報告的健檢紀錄：指定的那筆、同類別未完成的那筆，或新建一筆。"""
        Check = self.env['linkdot.health.check']
        if self.check_id:
            self.check_id.check_access('read')
            return self.check_id
        check = Check.search([
            ('employee_id', '=', self.employee_id.id),
            ('check_type', '=', self.check_type),
            ('state', 'in', ('draft', 'scheduled', 'reported')),
        ], order='scheduled_date, id', limit=1)
        return check or Check.sudo().create({
            'employee_id': self.employee_id.id,
            'check_type': self.check_type,
            'special_hazard': self.special_hazard,
            'check_date': self.check_date,
        })

    def action_upload(self):
        self.ensure_one()
        # 一般員工只能替自己上傳；健康管理人員可替任何人上傳
        if not self.env.user.has_group(OFFICER_GROUP) and self.employee_id != self.env.user.employee_id:
            raise AccessError(_("You can only upload your own health check reports."))
        if not self.file:
            raise UserError(_("Please choose the scanned report file."))
        check = self._get_or_create_check().sudo()
        if check.state != 'done':
            vals = {'check_date': self.check_date}
            if check.state in ('draft', 'scheduled'):
                vals['state'] = 'reported'
            if self.check_type == 'special' and self.special_hazard and not check.special_hazard:
                vals['special_hazard'] = self.special_hazard
            check.write(vals)
        report = self.env['linkdot.health.check.report']._upload(
            check, self.filename, base64.b64decode(self.file))
        # 檔案只留在雲端硬碟
        self.write({'file': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Report uploaded to Google Drive as %s.", report.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

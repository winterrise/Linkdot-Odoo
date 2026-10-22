import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import DriveError, SharedDriveClient

_logger = logging.getLogger(__name__)

PARAM_FOLDER = 'linkdot_health_check.drive_folder_id'
PARAM_CREDENTIALS = 'linkdot_health_check.drive_credentials'
ALLOWED_EXTENSIONS = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
MAX_SIZE_MB = 20
# 標準檔名固定用中文類別名，不受使用者介面語言影響
FILE_TYPE_LABELS = {
    'pre_employment': '新進人員體格檢查',
    'general': '一般健康檢查',
    'special': '特殊健康檢查',
    'other': '其他健康檢查',
}


class LinkdotHealthCheckReport(models.Model):
    """健檢報告：檔案只放在共用雲端硬碟，這裡只記檔名與連結。"""
    _name = 'linkdot.health.check.report'
    _description = 'Health Check Report'
    _order = 'create_date desc, id desc'

    check_id = fields.Many2one(
        'linkdot.health.check', string='Health Check', required=True, index=True, ondelete='restrict')
    employee_id = fields.Many2one(related='check_id.employee_id', store=True)
    company_id = fields.Many2one(related='check_id.company_id', store=True)
    name = fields.Char(string='File Name', required=True, readonly=True)
    drive_file_id = fields.Char(string='Google Drive File ID', readonly=True, copy=False)
    drive_url = fields.Char(string='Google Drive Link', readonly=True, copy=False)
    file_size = fields.Integer(string='Size (bytes)', readonly=True)

    @api.model
    def _get_drive_client(self):
        params = self.env['ir.config_parameter'].sudo()
        try:
            return SharedDriveClient(params.get_param(PARAM_CREDENTIALS), params.get_param(PARAM_FOLDER))
        except DriveError as e:
            raise UserError(_("Google Drive is not set up for health check reports yet. "
                              "Please ask a Health Check Administrator. (%s)", e)) from e

    @api.model
    def _standard_base_name(self, check):
        """員工編號_檢查類別_檢查日期，例：0013_一般健康檢查_20261022（不含姓名）。"""
        employee = check.employee_id.sudo()
        if not employee.barcode:
            raise UserError(_("%s has no employee number (Badge ID), so the report cannot be named. "
                              "Please ask HR to fill it in.", employee.name))
        if not check.check_date:
            raise UserError(_("Please set the check date first."))
        return '%s_%s_%s' % (employee.barcode, FILE_TYPE_LABELS[check.check_type],
                             check.check_date.strftime('%Y%m%d'))

    @api.model
    def _upload(self, check, original_filename, content):
        """上傳到 共用雲端硬碟/<檢查年度>/<標準檔名>，同名時加 _2、_3。"""
        extension = ('.' + original_filename.rsplit('.', 1)[-1].lower()) if '.' in (original_filename or '') else ''
        if extension not in ALLOWED_EXTENSIONS:
            raise UserError(_("Please upload a PDF, JPG or PNG file."))
        if len(content) > MAX_SIZE_MB * 1024 * 1024:
            raise UserError(_("The file is larger than %s MB.", MAX_SIZE_MB))
        base = self._standard_base_name(check)
        client = self._get_drive_client()
        try:
            folder_id = client.get_or_create_folder(str(check.check_date.year))
            taken = client.existing_names(folder_id, base)
            name, n = base + extension, 1
            while name in taken:
                n += 1
                name = '%s_%d%s' % (base, n, extension)
            uploaded = client.upload(folder_id, name, content, ALLOWED_EXTENSIONS[extension])
        except UserError:
            raise
        except Exception as e:
            _logger.exception("Health check report upload to Google Drive failed")
            raise UserError(_("Uploading to Google Drive failed: %s", e)) from e
        return self.sudo().create({
            'check_id': check.id,
            'name': uploaded.get('name', name),
            'drive_file_id': uploaded['id'],
            'drive_url': uploaded.get('webViewLink'),
            'file_size': int(uploaded.get('size') or len(content)),
        })

    def action_open_drive(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': self.drive_url, 'target': 'new'}

    @api.ondelete(at_uninstall=False)
    def _unlink_only_manager(self):
        if not self.env.user.has_group('linkdot_health_check.group_health_check_manager'):
            raise UserError(_("Health check reports must be retained and can only be deleted by a Health Check Administrator."))

    def unlink(self):
        files = [r.drive_file_id for r in self if r.drive_file_id]
        res = super().unlink()
        if files:
            client = self._get_drive_client()
            for file_id in files:
                client.trash(file_id)
        return res

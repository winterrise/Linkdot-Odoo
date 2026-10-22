from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools import DriveError, SharedDriveClient, parse_folder_id, service_account_email
from .linkdot_health_check_report import PARAM_CREDENTIALS, PARAM_FOLDER


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    health_check_reminder_days = fields.Integer(
        string='Remind Days Before Due', default=60,
        config_parameter='linkdot_health_check.reminder_days')
    health_check_drive_folder = fields.Char(
        string='Shared Drive Folder', config_parameter=PARAM_FOLDER,
        help="Paste the Shared Drive (or a folder inside it) link from the browser, or its ID. "
             "Reports go into a sub-folder per year.")
    health_check_drive_credentials = fields.Char(
        string='Service Account Key', config_parameter=PARAM_CREDENTIALS,
        help="Contents of the JSON key file of the Google Cloud service account.")
    health_check_drive_account = fields.Char(
        string='Service Account', compute='_compute_health_check_drive_account',
        help="Add this address to the Shared Drive as Content manager.")

    @api.depends('health_check_drive_credentials')
    def _compute_health_check_drive_account(self):
        for settings in self:
            settings.health_check_drive_account = service_account_email(settings.health_check_drive_credentials)

    @api.onchange('health_check_drive_folder')
    def _onchange_health_check_drive_folder(self):
        # 貼上網址時只存資料夾 ID
        folder_id = parse_folder_id(self.health_check_drive_folder)
        if folder_id != self.health_check_drive_folder:
            self.health_check_drive_folder = folder_id

    def set_values(self):
        self.health_check_drive_folder = parse_folder_id(self.health_check_drive_folder) or False
        super().set_values()

    def action_health_check_test_drive(self):
        self.ensure_one()
        try:
            client = SharedDriveClient(self.health_check_drive_credentials, self.health_check_drive_folder)
            name = client.check_access()
        except DriveError as e:
            raise UserError(str(e)) from e
        except Exception as e:
            raise UserError(_(
                "The service account cannot open this folder. Check that the folder link is right and that "
                "%(account)s is a member of the Shared Drive.\n\n%(error)s",
                account=self.health_check_drive_account or _("the service account"), error=e)) from e
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': _("Connected to Google Drive folder “%s”.", name)},
        }

import base64
import re
from datetime import date
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.linkdot_health_check.tools import SharedDriveClient, parse_folder_id

ROOT = 'SHARED_DRIVE_ROOT'
PDF = b'%PDF-1.4 scanned report'


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeDrive:
    """Just enough of googleapiclient's files() API for SharedDriveClient."""

    def __init__(self):
        self.files_by_id = {ROOT: {'id': ROOT, 'name': 'Health Reports', 'parents': [], 'mimeType': 'drive'}}
        self.trashed = set()
        self.uploads = []

    def files(self):
        return self

    def list(self, q, **kwargs):
        def match(f):
            if f['id'] in self.trashed or f['id'] == ROOT:
                return False
            for name in re.findall(r"name = '((?:[^'\\]|\\.)*)'", q):
                if f['name'] != name:
                    return False
            for part in re.findall(r"name contains '((?:[^'\\]|\\.)*)'", q):
                if part not in f['name']:
                    return False
            for parent in re.findall(r"'([^']+)' in parents", q):
                if parent not in f['parents']:
                    return False
            for mimetype in re.findall(r"mimeType = '([^']+)'", q):
                if f['mimeType'] != mimetype:
                    return False
            return True
        return _Request({'files': [f for f in self.files_by_id.values() if match(f)]})

    def create(self, body, media_body=None, **kwargs):
        file_id = 'F%d' % len(self.files_by_id)
        meta = dict(body, id=file_id, mimeType=body.get('mimeType') or media_body.mimetype())
        if media_body is not None:
            content = media_body.getbytes(0, media_body.size())
            meta.update(size=str(len(content)), webViewLink='https://drive.google.com/file/d/%s/view' % file_id)
            self.uploads.append((file_id, body['name'], content))
        self.files_by_id[file_id] = meta
        return _Request(meta)

    def get(self, fileId, **kwargs):
        if fileId not in self.files_by_id:
            raise Exception("File not found: %s" % fileId)
        return _Request(self.files_by_id[fileId])

    def update(self, fileId, body, **kwargs):
        if body.get('trashed'):
            self.trashed.add(fileId)
        return _Request(self.files_by_id[fileId])

    def folder(self, name, parent=ROOT):
        return [f for f in self.files_by_id.values()
                if f['name'] == name and parent in f['parents'] and f['mimeType'].endswith('folder')]


@tagged('post_install', '-at_install')
class TestReportUpload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env['ir.config_parameter']
        params.set_param('linkdot_health_check.drive_folder_id', ROOT)
        params.set_param('linkdot_health_check.drive_credentials', '{"client_email": "odoo@proj.iam.gserviceaccount.com"}')
        cls.officer = new_test_user(
            cls.env, login='up_officer', groups='base.group_user,linkdot_health_check.group_health_check_officer')
        cls.manager = new_test_user(
            cls.env, login='up_manager', groups='base.group_user,linkdot_health_check.group_health_check_manager')
        cls.staff_user = new_test_user(cls.env, login='up_staff', groups='base.group_user')
        cls.other_user = new_test_user(cls.env, login='up_other', groups='base.group_user')
        Employee = cls.env['hr.employee']
        cls.staff = Employee.create({'name': 'Staff', 'user_id': cls.staff_user.id, 'barcode': '0013'})
        cls.other = Employee.create({'name': 'Other', 'user_id': cls.other_user.id, 'barcode': '0027'})
        cls.Check = cls.env['linkdot.health.check']
        cls.Report = cls.env['linkdot.health.check.report']

    def setUp(self):
        super().setUp()
        self.drive = FakeDrive()
        patcher = patch.object(SharedDriveClient, '_build_service', return_value=self.drive)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, user, filename='scan.pdf', content=PDF, **vals):
        Wizard = self.env['linkdot.health.check.report.upload'].with_user(user)
        if 'check_id' in vals:
            Wizard = Wizard.with_context(default_check_id=vals.pop('check_id'))
        wizard = Wizard.create(dict({
            'check_date': date(2026, 10, 22),
            'file': base64.b64encode(content),
            'filename': filename,
        }, **vals))
        wizard.action_upload()
        return wizard

    def test_parse_folder_id(self):
        self.assertEqual(parse_folder_id('0AbCdEf_-123'), '0AbCdEf_-123')
        self.assertEqual(parse_folder_id(' https://drive.google.com/drive/folders/1AbC-d_E?usp=sharing '), '1AbC-d_E')
        self.assertEqual(parse_folder_id('https://drive.google.com/drive/u/0/folders/0AXyz'), '0AXyz')
        self.assertEqual(parse_folder_id('https://drive.google.com/open?id=1Qwe'), '1Qwe')

    def test_employee_upload_creates_check_and_names_file(self):
        wizard = self._upload(self.staff_user)
        check = self.Check.search([('employee_id', '=', self.staff.id)])
        self.assertEqual(len(check), 1)
        self.assertEqual(check.state, 'reported')
        self.assertEqual(check.check_date, date(2026, 10, 22))
        [report] = check.report_ids
        self.assertEqual(report.name, '0013_一般健康檢查_20261022.pdf')
        [year_folder] = self.drive.folder('2026')
        self.assertEqual(self.drive.uploads, [(report.drive_file_id, report.name, PDF)])
        self.assertEqual(self.drive.files_by_id[report.drive_file_id]['parents'], [year_folder['id']])
        self.assertTrue(report.drive_url)
        # 檔案不留在 Odoo
        self.assertFalse(wizard.file)
        self.assertFalse(self.env['ir.attachment'].search([
            ('res_model', 'in', ('linkdot.health.check', 'linkdot.health.check.report',
                                 'linkdot.health.check.report.upload'))]))

    def test_same_day_second_file_gets_suffix_and_reuses_folder(self):
        self._upload(self.staff_user)
        self._upload(self.staff_user, filename='page2.JPG', content=b'jpeg')
        names = sorted(self.Report.search([('employee_id', '=', self.staff.id)]).mapped('name'))
        self.assertEqual(names, ['0013_一般健康檢查_20261022.jpg', '0013_一般健康檢查_20261022.pdf'])
        self._upload(self.staff_user, filename='again.pdf')
        self.assertIn('0013_一般健康檢查_20261022_2.pdf',
                      self.Report.search([('employee_id', '=', self.staff.id)]).mapped('name'))
        self.assertEqual(len(self.drive.folder('2026')), 1)
        self.assertEqual(len(self.Check.search([('employee_id', '=', self.staff.id)])), 1)

    def test_upload_attaches_to_open_check_of_same_type(self):
        scheduled = self.Check.create({
            'employee_id': self.staff.id, 'scheduled_date': date(2026, 10, 20), 'state': 'scheduled'})
        self._upload(self.staff_user)
        self.assertEqual(scheduled.state, 'reported')
        self.assertEqual(scheduled.check_date, date(2026, 10, 22))
        self.assertEqual(len(scheduled.report_ids), 1)
        self._upload(self.staff_user, check_type='special', special_hazard='Noise')
        special = self.Check.search([('employee_id', '=', self.staff.id), ('check_type', '=', 'special')])
        self.assertEqual(special.report_ids.name, '0013_特殊健康檢查_20261022.pdf')

    def test_employee_cannot_upload_for_someone_else(self):
        with self.assertRaises(AccessError):
            self._upload(self.staff_user, employee_id=self.other.id)
        other_check = self.Check.create({'employee_id': self.other.id})
        with self.assertRaises(AccessError):
            self._upload(self.staff_user, check_id=other_check.id)
        self.assertFalse(self.drive.uploads)

    def test_officer_uploads_on_record_without_changing_done_state(self):
        check = self.Check.create({
            'employee_id': self.other.id, 'check_date': date(2025, 3, 10), 'state': 'done'})
        self._upload(self.officer, check_id=check.id, check_date=date(2025, 3, 10))
        self.assertEqual(check.state, 'done')
        self.assertEqual(check.report_ids.name, '0027_一般健康檢查_20250310.pdf')
        self.assertTrue(self.drive.folder('2025'))

    def test_rejections(self):
        with self.assertRaisesRegex(UserError, 'PDF'):
            self._upload(self.staff_user, filename='report.docx')
        self.staff.barcode = False
        with self.assertRaises(UserError):
            self._upload(self.staff_user)
        self.staff.barcode = '0013'
        self.env['ir.config_parameter'].set_param('linkdot_health_check.drive_folder_id', '')
        with self.assertRaises(UserError):
            self._upload(self.staff_user)
        self.assertFalse(self.drive.uploads)

    def test_report_visibility_and_deletion(self):
        self._upload(self.staff_user)
        self._upload(self.other_user)
        own = self.Report.with_user(self.staff_user).search([])
        self.assertEqual(own.employee_id, self.staff)
        self.assertEqual(len(self.Report.with_user(self.officer).search([])), 2)
        with self.assertRaises(AccessError):
            own.with_user(self.officer).unlink()
        file_id = own.drive_file_id
        own.with_user(self.manager).unlink()
        self.assertIn(file_id, self.drive.trashed)

    def test_settings_test_connection(self):
        settings = self.env['res.config.settings'].create({
            'health_check_drive_folder': 'https://drive.google.com/drive/folders/%s?usp=sharing' % ROOT,
            'health_check_drive_credentials': '{"client_email": "odoo@proj.iam.gserviceaccount.com"}',
        })
        self.assertEqual(settings.health_check_drive_account, 'odoo@proj.iam.gserviceaccount.com')
        result = settings.action_health_check_test_drive()
        self.assertIn('Health Reports', result['params']['message'])
        settings.execute()
        self.assertEqual(self.env['ir.config_parameter'].get_param('linkdot_health_check.drive_folder_id'), ROOT)
        settings = self.env['res.config.settings'].create({'health_check_drive_folder': 'WRONG'})
        with self.assertRaises(UserError):
            settings.action_health_check_test_drive()

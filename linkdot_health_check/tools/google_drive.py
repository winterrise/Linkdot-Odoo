"""Minimal Google Drive client for a Shared Drive, authenticated with a service account.

Only uses packages shipped in the Odoo image (google-api-python-client, google-auth).
"""
import io
import json
import re

DRIVE_SCOPES = ['https://www.googleapis.com/auth/drive']
FOLDER_MIMETYPE = 'application/vnd.google-apps.folder'


class DriveError(Exception):
    pass


def _quote(value):
    return value.replace('\\', '\\\\').replace("'", "\\'")


_FOLDER_URL = re.compile(r'/(?:folders|drives)/([A-Za-z0-9_-]+)')


def parse_folder_id(value):
    """接受資料夾 ID，或從瀏覽器複製的共用雲端硬碟／資料夾網址
    （https://drive.google.com/drive/folders/<id>?usp=... 或 .../drive/u/0/folders/<id>）。"""
    value = (value or '').strip()
    match = _FOLDER_URL.search(value)
    if match:
        return match.group(1)
    match = re.search(r'[?&]id=([A-Za-z0-9_-]+)', value)
    return match.group(1) if match else value


def service_account_email(credentials_json):
    try:
        return json.loads(credentials_json or '{}').get('client_email') or ''
    except ValueError:
        return ''


class SharedDriveClient:

    def __init__(self, credentials_json, root_folder_id, service=None):
        """root_folder_id: a Shared Drive id, or a folder id inside one."""
        if not root_folder_id:
            raise DriveError("Google Drive folder ID is not configured.")
        self.root_folder_id = parse_folder_id(root_folder_id)
        self.service = service or self._build_service(credentials_json)

    @staticmethod
    def _build_service(credentials_json):
        if not credentials_json:
            raise DriveError("Google service account key is not configured.")
        # 延後 import：沒用到雲端硬碟時不載入 Google 套件
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        try:
            info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
        except (ValueError, KeyError) as e:
            raise DriveError("Invalid Google service account key: %s" % e) from e
        return build('drive', 'v3', credentials=credentials, cache_discovery=False)

    def _list(self, query, fields='files(id, name)'):
        result = self.service.files().list(
            q=query, fields=fields, pageSize=1000,
            supportsAllDrives=True, includeItemsFromAllDrives=True, corpora='allDrives',
        ).execute()
        return result.get('files', [])

    def check_access(self):
        """Return the root folder (or Shared Drive) name; raises if the service account cannot reach it."""
        meta = self.service.files().get(
            fileId=self.root_folder_id, fields='id, name, mimeType', supportsAllDrives=True).execute()
        return meta.get('name')

    def get_or_create_folder(self, name, parent_id=None):
        parent_id = parent_id or self.root_folder_id
        found = self._list(
            "name = '%s' and mimeType = '%s' and '%s' in parents and trashed = false"
            % (_quote(name), FOLDER_MIMETYPE, _quote(parent_id)))
        if found:
            return found[0]['id']
        folder = self.service.files().create(
            body={'name': name, 'mimeType': FOLDER_MIMETYPE, 'parents': [parent_id]},
            fields='id', supportsAllDrives=True).execute()
        return folder['id']

    def existing_names(self, folder_id, prefix):
        return {f['name'] for f in self._list(
            "name contains '%s' and '%s' in parents and trashed = false" % (_quote(prefix), _quote(folder_id)))}

    def upload(self, folder_id, filename, content, mimetype):
        from googleapiclient.http import MediaIoBaseUpload
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)
        return self.service.files().create(
            body={'name': filename, 'parents': [folder_id]}, media_body=media,
            fields='id, name, webViewLink, size', supportsAllDrives=True).execute()

    def trash(self, file_id):
        self.service.files().update(fileId=file_id, body={'trashed': True}, supportsAllDrives=True).execute()

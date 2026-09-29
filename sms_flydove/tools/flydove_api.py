"""Minimal client for the Flydove (飛信資訊) SmartDove transactional SMS API.

API docs: https://documenter.getpostman.com/view/32479177/2sA3XY7JPs
  POST {endpoint}/api/v1/transactional_sms   {"content": str, "destinations": [{"to": E.164}]}  -> {"batch_id": str}
  GET  {endpoint}/api/v1/transactional_sms?batch_id=..&page=..&per_page=..
       -> {"data": [{"id", "to", "content", "code", "description"}], "meta": {"next_page"}}
Auth: "Authorization: Bearer <Admin API Token>". Rate limit 3600 calls / minute.
"""
import re

import requests

DEFAULT_ENDPOINT = 'https://clientapi.flydove.net'
MAX_DESTINATIONS = 100  # per POST, documented limit

# Delivery status codes returned by the query API
CODES_PENDING = {1000, 2000, 2001}  # queued, sending, delivered to carrier
CODE_DELIVERED = 2002
# final failures -> Odoo sms.tracker provider error (see sms.sms.DELIVERY_ERRORS)
CODES_FAILED = {
    4001: 'invalid_destination',  # 無效的手機號碼
    4002: 'rejected',             # 內容、資料有錯誤
    4003: 'invalid_destination',  # 門號有錯誤
    4004: 'not_allowed',          # 門號、簡訊已停用
    4005: 'rejected',             # 無效參數
    4030: 'not_allowed',          # 黑名單
    4080: 'expired',              # 逾時無法送達
    5000: 'not_delivered',        # 未定義的錯誤
    5001: 'not_delivered',        # 網路傳輸問題
}


class FlydoveApiError(Exception):
    def __init__(self, message, state):
        super().__init__(message)
        # state uses sms.sms IAP vocabulary so the standard post-processing can map it
        self.state = state


def to_e164(number):
    """Return an E.164 number ('+886912345678') or False if it cannot be derived.

    Odoo normally stores sanitized E.164 numbers already; local Taiwanese
    mobile numbers ('0912-345-678') are converted as a convenience.
    """
    if not number:
        return False
    number = number.strip()
    digits = re.sub(r'\D', '', number)
    if number.startswith('+'):
        e164 = '+' + digits
    elif digits.startswith('00'):
        e164 = '+' + digits[2:]
    elif len(digits) == 10 and digits.startswith('09'):
        e164 = '+886' + digits[1:]
    else:
        return False
    if e164.startswith('+8860'):  # '+886 0912…' typed with the trunk zero
        e164 = '+886' + e164[5:]
    return e164 if 8 <= len(e164) <= 16 else False


def digits_only(number):
    return re.sub(r'\D', '', number or '')


class FlydoveSmsApi:

    def __init__(self, token, endpoint=DEFAULT_ENDPOINT, timeout=15):
        self.token = token
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip('/')
        self.timeout = timeout

    def _headers(self):
        return {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}',
        }

    def _request(self, method, path, **kwargs):
        if not self.token:
            raise FlydoveApiError('Flydove API token is not set', 'unregistered')
        try:
            response = requests.request(
                method, self.endpoint + path, headers=self._headers(), timeout=self.timeout, **kwargs)
        except requests.exceptions.RequestException as e:
            raise FlydoveApiError(f'Flydove API unreachable: {e}', 'server_error') from e
        if response.status_code in (401, 403):
            raise FlydoveApiError(f'Flydove API rejected the token (HTTP {response.status_code})', 'unregistered')
        if response.status_code >= 400:
            state = 'server_error' if response.status_code >= 500 else f'flydove_http_{response.status_code}'
            raise FlydoveApiError(
                f'Flydove API error HTTP {response.status_code}: {response.text[:500]}', state)
        try:
            return response.json()
        except ValueError as e:
            raise FlydoveApiError(f'Flydove API returned non-JSON: {response.text[:200]}', 'server_error') from e

    def send(self, content, numbers):
        """Send one content to up to MAX_DESTINATIONS E.164 numbers; return the batch id."""
        if len(numbers) > MAX_DESTINATIONS:
            raise ValueError('Too many destinations for one Flydove call')
        result = self._request('POST', '/api/v1/transactional_sms', json={
            'content': content,
            'destinations': [{'to': number} for number in numbers],
        })
        batch_id = result.get('batch_id')
        if not batch_id:
            raise FlydoveApiError(f'Flydove API response without batch_id: {result}', 'server_error')
        return batch_id

    def get_batch_statuses(self, batch_id, per_page=100):
        """Return every message of a batch as a list of dicts (to, code, description)."""
        messages, page = [], 1
        while True:
            result = self._request('GET', '/api/v1/transactional_sms', params={
                'batch_id': batch_id, 'page': page, 'per_page': per_page,
            })
            messages += result.get('data') or []
            if not (result.get('meta') or {}).get('next_page'):
                return messages
            page += 1

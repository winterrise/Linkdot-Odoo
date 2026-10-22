import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# 逗號分隔的網域；未設定或清空即停用以 Email 自動綁定
ALLOWED_DOMAINS_PARAM = 'linkdot_auth_oauth_email.allowed_domains'


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        # 官方只用 OAuth 的 subject（Google 的 sub）找帳號；事先建好、還沒綁過的帳號
        # 第一次登入時改用「已驗證的 Email」對應，綁定後就回到官方流程。
        oauth_uid = validation['user_id']
        if not self.search_count([('oauth_uid', '=', oauth_uid), ('oauth_provider_id', '=', provider)]):
            user = self._linkdot_find_user_by_oauth_email(provider, validation)
            if user:
                user.write({'oauth_provider_id': provider, 'oauth_uid': oauth_uid})
                _logger.info("OAuth: bound provider %s subject to user %s (%s) by verified email",
                             provider, user.id, user.login)
        return super()._auth_oauth_signin(provider, validation, params)

    @api.model
    def _linkdot_get_oauth_allowed_domains(self):
        value = self.env['ir.config_parameter'].sudo().get_param(ALLOWED_DOMAINS_PARAM) or ''
        return {d.strip().lower().lstrip('@') for d in value.split(',') if d.strip()}

    @api.model
    def _linkdot_find_user_by_oauth_email(self, provider, validation):
        email = (validation.get('email') or '').strip().lower()
        if not email or validation.get('email_verified') is not True:
            return self.browse()
        if email.rpartition('@')[2] not in self._linkdot_get_oauth_allowed_domains():
            return self.browse()
        users = self.search([('login', '=', email), ('share', '=', False)])
        # 已綁過其他 OAuth 身分的帳號不改綁，避免 Email 被重新使用時帳號被接管
        users = users.filtered(lambda u: not u.oauth_uid
                               and u.oauth_provider_id.id in (False, provider))
        return users if len(users) == 1 else self.browse()

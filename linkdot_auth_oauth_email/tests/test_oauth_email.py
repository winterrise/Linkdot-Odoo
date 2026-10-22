import json

from odoo.exceptions import AccessDenied
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestOAuthEmailSignin(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].set_param('linkdot_auth_oauth_email.allowed_domains', 'example.com')
        # 不允許自行註冊，對應不到帳號時官方流程必須拒絕
        cls.env['ir.config_parameter'].set_param('auth_signup.invitation_scope', 'b2b')
        cls.provider = cls.env.ref('auth_oauth.provider_google')
        cls.user = new_test_user(cls.env, login='staff@example.com', groups='base.group_user')
        cls.Users = cls.env['res.users'].sudo()

    def _signin(self, sub='google-sub-1', email='staff@example.com', verified=True):
        validation = {'user_id': sub, 'email': email, 'email_verified': verified, 'name': 'Staff'}
        params = {'access_token': 'token', 'state': json.dumps({})}
        return self.Users._auth_oauth_signin(self.provider.id, validation, params)

    def test_first_login_binds_by_verified_email(self):
        self.assertEqual(self._signin(), 'staff@example.com')
        self.assertEqual(self.user.oauth_uid, 'google-sub-1')
        self.assertEqual(self.user.oauth_provider_id, self.provider)
        # 第二次走官方的 subject 對應
        self.assertEqual(self._signin(email='renamed@example.com'), 'staff@example.com')

    def test_email_is_case_insensitive(self):
        self.assertEqual(self._signin(email='Staff@Example.com'), 'staff@example.com')

    def test_unverified_email_rejected(self):
        with self.assertRaises(AccessDenied):
            self._signin(verified=False)
        self.assertFalse(self.user.oauth_uid)

    def test_other_domain_rejected(self):
        new_test_user(self.env, login='someone@gmail.com', groups='base.group_user')
        with self.assertRaises(AccessDenied):
            self._signin(email='someone@gmail.com')

    def test_empty_allowed_domains_disables_binding(self):
        self.env['ir.config_parameter'].set_param('linkdot_auth_oauth_email.allowed_domains', '')
        with self.assertRaises(AccessDenied):
            self._signin()

    def test_already_bound_user_not_rebound(self):
        self.user.oauth_uid = 'google-sub-old'
        with self.assertRaises(AccessDenied):
            self._signin(sub='google-sub-new')
        self.assertEqual(self.user.oauth_uid, 'google-sub-old')

    def test_archived_user_not_matched(self):
        self.user.active = False
        with self.assertRaises(AccessDenied):
            self._signin()

    def test_portal_user_not_matched(self):
        new_test_user(self.env, login='portal@example.com', groups='base.group_portal')
        with self.assertRaises(AccessDenied):
            self._signin(email='portal@example.com')


@tagged('post_install', '-at_install')
class TestOAuthOnlyLoginPage(HttpCase):

    def test_login_page(self):
        self.env['auth.oauth.provider'].search([]).write({'enabled': False})
        provider = self.env.ref('auth_oauth.provider_google')
        page = self.url_open('/web/login').text
        self.assertIn('name="password"', page, "without OAuth providers the password form must stay")

        provider.write({'enabled': True, 'client_id': 'test-client-id'})
        page = self.url_open('/web/login').text
        self.assertNotIn('name="password"', page)
        self.assertIn('accounts.google.com', page)

        page = self.url_open('/web/login?password_login=1').text
        self.assertIn('name="password"', page)
        self.assertIn('name="password_login"', page)

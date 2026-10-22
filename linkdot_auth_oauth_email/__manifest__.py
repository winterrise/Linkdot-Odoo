{
    'name': 'OAuth Login: Match Existing Users by Email',
    'version': '18.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Bind the first OAuth (Google) login to the existing user with the same verified email, and show only OAuth buttons on the login page',
    'author': 'Linkdot',
    'license': 'LGPL-3',
    'depends': ['auth_oauth'],
    'data': [
        'views/auth_oauth_templates.xml',
    ],
    'installable': True,
    'application': False,
}

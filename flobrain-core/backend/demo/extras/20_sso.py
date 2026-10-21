"""SSO in the demo: SAML through the demo identity provider (see ``demo/idp.py``)."""


def seed(org, users, now):
    from demo import idp

    idp.configure(org)

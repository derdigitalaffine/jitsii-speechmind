from app import main


def _form_action(policy: str) -> str:
    return next(part.strip() for part in policy.split(';') if part.strip().startswith('form-action '))


def test_csp_allows_configured_portal_and_meet_origins(monkeypatch):
    monkeypatch.setattr(main.settings, 'portal_base_url', 'https://portal.example.org/some/path')
    monkeypatch.setattr(main.settings, 'meet_base_url', 'https://meet.example.org/another/path')

    assert _form_action(main.build_csp()) == (
        "form-action 'self' https://portal.example.org https://meet.example.org"
    )


def test_csp_deduplicates_equal_configured_origins(monkeypatch):
    monkeypatch.setattr(main.settings, 'portal_base_url', 'https://portal.example.org')
    monkeypatch.setattr(main.settings, 'meet_base_url', 'https://portal.example.org/')

    assert _form_action(main.build_csp()) == "form-action 'self' https://portal.example.org"

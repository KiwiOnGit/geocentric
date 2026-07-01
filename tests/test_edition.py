import pytest

from geocentric import edition


@pytest.fixture(autouse=True)
def isolated_entitlement(tmp_path, monkeypatch):
    monkeypatch.setattr(edition, "ENTITLEMENT_PATH", tmp_path / "entitlement.json")
    yield


def test_default_is_free():
    assert edition.get_entitlement().edition == "free"
    assert not edition.is_pro()
    assert edition.edition_label() == "Free"


def test_free_tier_gates():
    assert edition.max_turn_limit() == edition.FREE_TURN_LIMIT
    assert edition.max_effort() == "medium"
    assert edition.clamp_effort("max") == "medium"
    assert edition.clamp_effort("low") == "low"
    assert edition.provider_allowed("ollama")
    assert edition.provider_allowed("local")
    assert not edition.provider_allowed("anthropic")
    assert not edition.beta_allowed()
    assert not edition.coordinator_mode_allowed()
    assert not edition.plugins_allowed()


def test_activate_success_unlocks_pro():
    def fake_redeem(key):
        assert key == "TEST-KEY"
        return True, "ok"

    ok, message = edition.activate("TEST-KEY", fake_redeem)
    assert ok
    assert edition.is_pro()
    assert edition.max_turn_limit() == edition.PRO_TURN_LIMIT
    assert edition.max_effort() == "max"
    assert edition.provider_allowed("anthropic")
    assert edition.beta_allowed()


def test_activate_failure_stays_free():
    def fake_redeem(key):
        return False, "invalid_or_used_key"

    ok, message = edition.activate("BAD-KEY", fake_redeem)
    assert not ok
    assert not edition.is_pro()


def test_needs_reverify_false_for_free_users():
    assert not edition.needs_reverify()


def test_needs_reverify_false_immediately_after_activation():
    edition.activate("TEST-KEY", lambda k: (True, "ok"))
    assert not edition.needs_reverify()


def test_reverify_downgrades_on_revoked():
    edition.activate("TEST-KEY", lambda k: (True, "ok"))
    assert edition.is_pro()

    edition.reverify(lambda k: "revoked")
    assert not edition.is_pro()


def test_reverify_keeps_pro_on_network_error():
    edition.activate("TEST-KEY", lambda k: (True, "ok"))

    def flaky_check(k):
        raise ConnectionError("offline")

    edition.reverify(flaky_check)
    assert edition.is_pro()  # fails open


def test_reverify_noop_for_free_users():
    def check_fn(k):
        raise AssertionError("should not be called for free users")

    edition.reverify(check_fn)  # must not raise
    assert not edition.is_pro()


def test_deactivate_reverts_to_free():
    edition.activate("TEST-KEY", lambda k: (True, "ok"))
    assert edition.is_pro()
    edition.deactivate()
    assert not edition.is_pro()

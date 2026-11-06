import pytest

from app.core.passwords import check_strength, hash_password, verify_password


def test_roundtrip_and_salting():
    h1, h2 = hash_password("correct-horse"), hash_password("correct-horse")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password("correct-horse", h1)
    assert not verify_password("wrong", h1)


@pytest.mark.parametrize("stored", [None, "", "garbage", "bcrypt$1$2$3$4$5", "scrypt$x$y$z$!!$!!"])
def test_invalid_hash_never_verifies(stored):
    assert verify_password("anything", stored) is False


def test_strength():
    check_strength("long-enough-pw")
    with pytest.raises(ValueError):
        check_strength("short")

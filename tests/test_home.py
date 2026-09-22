"""Which of Yonatan's two addresses goes on an application.

He lives in Zichron Ya'akov and in Tel Aviv-Jaffa (confirmed 2026-09-22). Both
are true; the one a given employer should read is the near one, because a Haifa
recruiter seeing "Tel Aviv" reads a commute nobody makes.
"""
import pytest

import cvsender.config as config
from cvsender import home


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    from cvsender.db.migrations import migrate
    migrate()
    return {"location": "Tel Aviv, Israel", "email": "y@example.com"}


@pytest.mark.parametrize("place", [
    "Haifa, Haifa District, Israel", "Matam, Haifa", "Caesarea, Haifa District",
    "Yokneam Illit", "Karmiel, North District, Israel", "Nesher",
    "Tirat HaCarmel", "Binyamina", "Hadera", "חיפה", "מגדל העמק", "הקריות",
])
def test_a_northern_posting_gets_the_northern_address(db, place):
    from cvsender.db import store
    store.set_setting("home.base_north", "Zichron Ya'akov, Israel")
    assert home.profile_for(place, db)["location"] == "Zichron Ya'akov, Israel"


@pytest.mark.parametrize("place", [
    "Tel Aviv-Yafo, Israel", "Herzliya", "Petah Tikva", "Jerusalem",
    "Beer Sheva", "Remote", "", "London, United Kingdom",
    "Kiryat Gat",      # south, despite the "kiryat"
    "Kiryat Ono",      # centre, despite the "kiryat"
])
def test_everywhere_else_keeps_the_profile_address(db, place):
    assert home.profile_for(place, db)["location"] == "Tel Aviv, Israel"


def test_the_northern_address_is_a_setting_not_a_constant(db):
    from cvsender.db import store
    store.set_setting("home.base_north", "Binyamina, Israel")
    assert home.profile_for("Haifa", db)["location"] == "Binyamina, Israel"


def test_unset_means_one_address_for_everything(db):
    """No constant in a source file gets to decide where someone lives."""
    assert home.profile_for("Haifa, Israel", db)["location"] == "Tel Aviv, Israel"


def test_nothing_else_about_him_changes(db):
    from cvsender.db import store
    store.set_setting("home.base_north", "Zichron Ya'akov, Israel")
    out = home.profile_for("Haifa, Israel", db)
    assert out["email"] == db["email"]
    assert db["location"] == "Tel Aviv, Israel"      # the original is untouched


def test_the_second_address_round_trips_through_the_profile_api(db, monkeypatch):
    """It has to be visible and editable, or it is invisible magic."""
    from fastapi.testclient import TestClient
    from cvsender import main
    monkeypatch.setattr(main, "_cloud_bg", lambda *a, **k: None)
    with TestClient(main.app) as c:
        c.cookies.clear()
        from cvsender import auth
        token = auth.create_session()
        c.cookies.set("cvs_session", token)
        r = c.put("/api/profile", json={"full_name": "Yonatan Volsky",
                                        "email": "y@example.com",
                                        "location": "Tel Aviv, Israel",
                                        "location_north": "Zichron Ya'akov, Israel"})
        assert r.status_code == 200
        assert r.json()["location_north"] == "Zichron Ya'akov, Israel"
        assert c.get("/api/profile").json()["location_north"] == "Zichron Ya'akov, Israel"

        # blank turns it off: every application then uses the one address
        c.put("/api/profile", json={"full_name": "Yonatan Volsky",
                                    "email": "y@example.com",
                                    "location": "Tel Aviv, Israel",
                                    "location_north": ""})
        assert home.profile_for("Haifa, Israel",
                                {"location": "Tel Aviv, Israel"})["location"] == "Tel Aviv, Israel"

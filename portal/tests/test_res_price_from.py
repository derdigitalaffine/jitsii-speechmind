"""„ab … je …“ auf Ressourcenseite und im Katalog: nur eingeschaltete Buchungsarten zählen."""

from app import res_view
from app.db import Resource, ResourceUnit, SessionLocal

from conftest import client
from test_resources import make_resource, module_on, slug_of  # noqa: F401


def test_price_from_ignores_disabled_modes():
    rid = make_resource("Grill ohne Blöcke", units="day", price_day=10000, price_block=5000, price_hour=1000)
    with SessionLocal() as db:
        res = db.get(Resource, rid)
        assert res_view.price_from(res) == 10000 and res_view.price_from_unit(res) == "Tag"
        res.units = "day,block"
        assert res_view.price_from(res) == 5000 and res_view.price_from_unit(res) == "Block"
        res.units = "hour"
        res.price_hour = 0
        res.parts.append(ResourceUnit(name="Kleiner Raum", price_hour=800, price_block=100))
        assert res_view.price_from(res) == 800 and res_view.price_from_unit(res) == "Std."
        db.rollback()
    page = client().get(f"/r/{slug_of(rid)}")
    assert "ab 100,00 €" in page.text and "je Tag" in page.text and "je Block" not in page.text
    assert "ab 50,00 €" not in client().get("/r").text.split("Grill ohne Blöcke")[1][:2000]

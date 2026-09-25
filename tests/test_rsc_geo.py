"""Flight data parsing and geometry. Offline."""

from pathlib import Path

from apartment_hunter import geo, rsc

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_resolves_references_and_text_rows():
    raw = '1:{"a":"$2","b":"$3"}\n2:["x",1]\n3:T5,hello4:null\n'
    data = rsc.parse(raw)
    assert data["1"] == {"a": ["x", 1], "b": "hello"}
    assert data["4"] is None


def test_text_row_length_counts_utf8_bytes():
    raw = '1:T6,café!2:"next"\n'
    data = rsc.parse(raw)
    assert data["1"] == "café!" and data["2"] == "next"


def test_module_rows_are_skipped():
    data = rsc.parse('1:I[123,["a"],"b"]\n2:HL["x"]\n3:{"ok":true}\n')
    assert data["1"] is None and data["2"] is None and data["3"] == {"ok": True}


def test_real_streeteasy_page_has_14_listings():
    data = rsc.parse((FIXTURES / "streeteasy_search_flight.txt").read_text())
    edges = rsc.find(list(data.values()), lambda o: str(o.get("__typename", "")).endswith("RentalEdge"))
    assert len({e["node"]["id"] for e in edges}) == 14


def test_polyline_known_value():
    assert geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_point_in_polygon_square():
    square = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
    assert geo.point_in_polygon(0.5, 0.5, square)
    assert not geo.point_in_polygon(1.5, 0.5, square)


def test_haversine_one_manhattan_block():
    # 14th St to 15th St on Seventh Avenue is about 80 m.
    assert 60 < geo.haversine_m(40.737826, -74.000201, 40.738550, -73.999680) < 110


def test_bbox_orders_south_west_north_east():
    assert geo.bbox([(1.0, 5.0), (3.0, 2.0)]) == (1.0, 2.0, 3.0, 5.0)

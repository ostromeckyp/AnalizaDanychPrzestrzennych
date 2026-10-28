def test_gravel_geojson(client):
    r = client.get("/api/gravel")
    assert r.status_code == 200
    f = r.json()["features"]
    assert len(f) == 1 and f[0]["geometry"]["type"] == "Polygon"
    assert f[0]["properties"]["attribution"] == "Obrys wg mapy KŻ Nysa (W. Wróblewski, 2023)"
    lon, lat = f[0]["geometry"]["coordinates"][0][0]
    assert 15 < lon < 20 and 49 < lat < 52          # EPSG:4326


def test_gravel_404_without_file(client_no_eval):
    assert client_no_eval.get("/api/gravel").status_code == 404

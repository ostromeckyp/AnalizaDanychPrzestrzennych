"""03 - Obrys jeziora, bufor AOI i przystanie z OpenStreetMap.

Co robi: pobiera z Overpass relację 2908769 (Jezioro Nyskie) oraz przystanie,
  slipy i pomosty w BBOX jeziora; zapisuje obrys, bufor 500 m i punkty.
Dlaczego tak: obrys z OSM jest darmowy i wystarczająco dokładny na maskę wody;
  bufor 500 m obejmuje brzeg i strefę przybrzeżną do analizy; surowy JSON jest
  cache'owany, więc skrypt jest powtarzalny i nie obciąża serwera (jedno zapytanie).
Wejście → wyjście: Overpass API → data/raw/osm/*.json,
  data/processed/lake.gpkg (warstwy lake, aoi), data/processed/marinas.gpkg.
Jak to obronić: wszystkie dane pochodzą z jawnego, odtwarzalnego zapytania;
  relacja multipolygon jest składana z ścieżek (polygonize), inner = wyspy/dziury.
"""
import geopandas as gpd

from mielizna import osm
from mielizna.config import data_path
from mielizna.grid import reference_grid

BBOX = "50.42,17.20,50.49,17.32"  # S,W,N,E z zapasem wokół jeziora
QUERY = f"""[out:json][timeout:120];
(
  relation({osm.LAKE_RELATION_ID});
  nwr["leisure"~"^(marina|slipway)$"]({BBOX});
  nwr["man_made"="pier"]({BBOX});
);
out geom;"""


def main():
    data = osm.fetch_overpass(QUERY)
    lake = osm.lake_polygon(data)
    out = data_path("processed", "lake.gpkg")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    gpd.GeoDataFrame(geometry=[lake], crs=osm.TARGET_CRS).to_file(out, layer="lake", driver="GPKG")
    gpd.GeoDataFrame(geometry=[lake.buffer(500)], crs=osm.TARGET_CRS).to_file(
        out, layer="aoi", driver="GPKG")

    pts = osm.points_gdf(data)
    m = data_path("processed", "marinas.gpkg")
    if m.exists():
        m.unlink()
    pts.to_file(m, driver="GPKG")

    ll = gpd.GeoSeries([lake], crs=osm.TARGET_CRS).to_crs(4326)
    print("Obrys (EPSG:4326) bounds:", [round(v, 5) for v in ll.total_bounds])
    print(f"Powierzchnia: {lake.area / 1e6:.2f} km2")
    print("Punkty wg rodzaju:", pts.kind.value_counts().to_dict())
    grid = reference_grid()
    print("Maska jeziora [px]:", int(osm.lake_mask(grid).sum()),
          "AOI [px]:", int(osm.aoi_mask(grid).sum()))


if __name__ == "__main__":
    main()

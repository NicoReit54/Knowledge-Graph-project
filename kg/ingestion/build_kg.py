"""
Vienna Mobility KG - ingestion script.

Rebuilds the full knowledge graph (TBox + ABox) from data/raw/ + data/processed/
and writes it to kg/vienna_mobility_kg.ttl.

Reusable/rerunnable version of the logic prototyped in
notebooks/02_kg_instantiation.ipynb - see that notebook for the exploratory,
cell-by-cell version.

Usage:
    python kg/ingestion/build_kg.py
"""

import re
import sys
from pathlib import Path

import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, RDF
from rdflib.namespace import XSD

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SCHEMA_TTL = ROOT / "kg" / "schema" / "ontology.ttl"
OUTPUT_TTL = ROOT / "kg" / "vienna_mobility_kg.ttl"

VIENNAKG = Namespace("http://example.org/viennakg#")
SCHEMA = Namespace("https://schema.org/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def safe_id(raw) -> str:
    """Turn a messy source ID (e.g. 'MUSEUMOGD.138686') into a URI-safe local name."""
    return re.sub(r"[^A-Za-z0-9_]", "_", str(raw))


def parse_point(shape):
    """Extract the first 'lon lat' pair out of a WKT SHAPE string."""
    m = re.search(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", str(shape))
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def bezirk_uri(bezirk):
    """BEZIRK int -> the matching viennakg:BezirkN individual, or None if missing."""
    if pd.isnull(bezirk):
        return None
    return VIENNAKG[f"Bezirk{int(bezirk)}"]


def add_geo(g, poi, shape):
    lon, lat = parse_point(shape)
    if lon is not None:
        g.add((poi, GEO.long, Literal(lon, datatype=XSD.decimal)))
        g.add((poi, GEO.lat, Literal(lat, datatype=XSD.decimal)))


def add_amenity(g, poi, label, value=True):
    """schema:amenityFeature -> schema:LocationFeatureSpecification(name, value).
    Covers both Park's boolean amenities and Playground's equipment list with
    one pattern - see docs/kg_schema_design.md."""
    feature = BNode()
    g.add((poi, SCHEMA.amenityFeature, feature))
    g.add((feature, RDF.type, SCHEMA.LocationFeatureSpecification))
    g.add((feature, SCHEMA.name, Literal(label)))
    g.add((feature, SCHEMA.value, Literal(bool(value), datatype=XSD.boolean)))


# --------------------------------------------------------------------------
# Per-source loaders - one function per row of docs/kg_schema_design.md's
# mapping table. Each returns the number of source rows processed.
# --------------------------------------------------------------------------

def load_museen(g):
    df = pd.read_csv(PROCESSED / "MUSEUMOGD_clean.csv")
    for _, row in df.iterrows():
        poi = VIENNAKG[f"museum_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, SCHEMA.Museum))
        g.add((poi, SCHEMA.name, Literal(row["NAME"])))
        g.add((poi, SCHEMA.address, Literal(row["ADRESSE"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        if pd.notnull(row.get("WEITERE_INF")):
            g.add((poi, SCHEMA.url, Literal(row["WEITERE_INF"])))
    return len(df)


def load_buechereien(g):
    df = pd.read_csv(RAW / "BUECHEREIOGD.csv")
    oeff_cols = [c for c in df.columns if c.startswith("OEFFNUNGSZEITEN")]
    for _, row in df.iterrows():
        poi = VIENNAKG[f"buecherei_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, SCHEMA.Library))
        g.add((poi, SCHEMA.name, Literal(row["NAME"])))
        g.add((poi, SCHEMA.address, Literal(row["ADRESSE"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        hours = "; ".join(str(row[c]) for c in oeff_cols if pd.notnull(row[c]))
        if hours:
            g.add((poi, SCHEMA.openingHours, Literal(hours)))
        if pd.notnull(row.get("TELEFON")):
            g.add((poi, SCHEMA.telephone, Literal(row["TELEFON"])))
        if pd.notnull(row.get("EMAIL")):
            g.add((poi, SCHEMA.email, Literal(row["EMAIL"])))
        if pd.notnull(row.get("WEBLINK1")):
            g.add((poi, SCHEMA.url, Literal(row["WEBLINK1"])))
    return len(df)


def load_badestellen(g):
    df = pd.read_csv(RAW / "BADESTELLENOGD.csv")
    for _, row in df.iterrows():
        poi = VIENNAKG[f"badestelle_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, VIENNAKG.BathingSite))
        g.add((poi, SCHEMA.name, Literal(row["BEZEICHNUNG"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
    return len(df)


def load_parks(g):
    df = pd.read_csv(PROCESSED / "PARKINFOOGD_clean.csv")
    amenity_map = {
        "SPIELEN_IM_PARK": "Playground",
        "WASSER_IM_PARK": "Water feature",
        "HUNDE_IM_PARK": "Dogs allowed",
    }
    for _, row in df.iterrows():
        poi = VIENNAKG[f"park_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, SCHEMA.Park))
        g.add((poi, SCHEMA.name, Literal(row["ANL_NAME"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        if pd.notnull(row.get("FLAECHE_M2")):
            g.add((poi, VIENNAKG.areaSqm, Literal(row["FLAECHE_M2"], datatype=XSD.decimal)))
        for col, label in amenity_map.items():
            val = str(row.get(col, "")).strip().lower() == "ja"
            add_amenity(g, poi, label, val)
    return len(df)


def load_schwimmbaeder(g):
    df = pd.read_csv(RAW / "SCHWIMMBADOGD.csv")
    for _, row in df.iterrows():
        poi = VIENNAKG[f"schwimmbad_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, VIENNAKG.SwimmingPool))
        g.add((poi, SCHEMA.name, Literal(row["NAME"])))
        g.add((poi, SCHEMA.address, Literal(row["ADRESSE"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        if pd.notnull(row.get("WEBLINK1")):
            g.add((poi, SCHEMA.url, Literal(row["WEBLINK1"])))
    return len(df)


def load_spielplaetze(g):
    """One PlaygroundArea instance per source row - deliberately not aggregated
    by ANL_NAME, per the 'separate nodes per feature' modelling decision."""
    df = pd.read_csv(RAW / "SPIELPLATZPUNKTOGD.csv")
    for _, row in df.iterrows():
        poi = VIENNAKG[f"playground_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, VIENNAKG.PlaygroundArea))
        g.add((poi, SCHEMA.name, Literal(row["ANL_NAME"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        detail = row.get("SPIELPLATZ_DETAIL")
        if pd.notnull(detail):
            for item in [x.strip() for x in str(detail).split(",") if x.strip()]:
                add_amenity(g, poi, item, True)
    return len(df)


def load_sights(g):
    df = pd.read_csv(PROCESSED / "WIENTOURISMUS_sights_clean.csv")
    subcat_to_concept = {
        "Sehenswürdigkeit": VIENNAKG.subcat_Sehenswuerdigkeit,
        "Schloss & Palais": VIENNAKG.subcat_SchlossPalais,
    }
    for _, row in df.iterrows():
        poi = VIENNAKG[f"sight_{safe_id(row['FID'])}"]
        g.add((poi, RDF.type, SCHEMA.TouristAttraction))
        g.add((poi, SCHEMA.name, Literal(row["NAME"])))
        if pd.notnull(row.get("STREET")):
            g.add((poi, SCHEMA.address, Literal(row["STREET"])))
        add_geo(g, poi, row["SHAPE"])
        bez = bezirk_uri(row["BEZIRK"])
        if bez is not None:
            g.add((poi, SCHEMA.containedInPlace, bez))
        concept = subcat_to_concept.get(row["SUBCATEGORY_NAME"])
        if concept is not None:
            g.add((poi, VIENNAKG.hasCategory, concept))
    return len(df)


def load_transport(g):
    """Three-way join: linien -> stops -> platforms, semicolon-delimited files
    with WGS84_LAT/LON columns instead of a WKT SHAPE string. See
    docs/wiener_linien_api_notes.md for the join path."""
    linien = pd.read_csv(RAW / "wienerlinien-ogd-linien.csv", sep=";")
    haltestellen = pd.read_csv(RAW / "wienerlinien-ogd-haltestellen.csv", sep=";")
    steige = pd.read_csv(RAW / "wienerlinien-ogd-steige.csv", sep=";")

    for _, row in linien.iterrows():
        line = VIENNAKG[f"line_{safe_id(row['LINIEN_ID'])}"]
        g.add((line, RDF.type, VIENNAKG.Line))
        g.add((line, SCHEMA.name, Literal(row["BEZEICHNUNG"])))
        if pd.notnull(row.get("VERKEHRSMITTEL")):
            g.add((line, VIENNAKG.mode, Literal(row["VERKEHRSMITTEL"])))

    for _, row in haltestellen.iterrows():
        stop = VIENNAKG[f"stop_{safe_id(row['HALTESTELLEN_ID'])}"]
        g.add((stop, RDF.type, VIENNAKG.Stop))
        g.add((stop, SCHEMA.name, Literal(row["NAME"])))
        g.add((stop, GEO.long, Literal(row["WGS84_LON"], datatype=XSD.decimal)))
        g.add((stop, GEO.lat, Literal(row["WGS84_LAT"], datatype=XSD.decimal)))

    n_rbl, n_no_rbl = 0, 0
    for _, row in steige.iterrows():
        platform = VIENNAKG[f"platform_{safe_id(row['STEIG_ID'])}"]
        stop = VIENNAKG[f"stop_{safe_id(row['FK_HALTESTELLEN_ID'])}"]
        line = VIENNAKG[f"line_{safe_id(row['FK_LINIEN_ID'])}"]
        g.add((platform, RDF.type, VIENNAKG.Platform))
        g.add((stop, VIENNAKG.hasPlatform, platform))
        g.add((platform, VIENNAKG.servedByLine, line))
        if pd.notnull(row.get("RBL_NUMMER")):
            g.add((platform, VIENNAKG.rbl, Literal(int(row["RBL_NUMMER"]), datatype=XSD.integer)))
            n_rbl += 1
        else:
            n_no_rbl += 1

    return {
        "lines": len(linien),
        "stops": len(haltestellen),
        "platforms": len(steige),
        "platforms_with_rbl": n_rbl,
        "platforms_without_rbl": n_no_rbl,
    }


POI_LOADERS = [
    ("Museen", load_museen),
    ("Büchereien", load_buechereien),
    ("Badestellen", load_badestellen),
    ("Parkanlagen", load_parks),
    ("Schwimmbäder", load_schwimmbaeder),
    ("Spielplätze", load_spielplaetze),
    ("Sights (Wien Tourismus)", load_sights),
]


def main():
    if not SCHEMA_TTL.exists():
        sys.exit(f"Ontology not found at {SCHEMA_TTL}.")

    g = Graph()
    g.parse(str(SCHEMA_TTL), format="turtle")
    g.bind("viennakg", VIENNAKG)
    g.bind("schema", SCHEMA)
    g.bind("geo", GEO)
    print(f"Loaded TBox: {len(g)} triples")

    print("\nPOI sources:")
    for label, loader in POI_LOADERS:
        n = loader(g)
        print(f"  {label:28} {n:>6} rows -> {len(g):>7} triples total")

    print("\nTransport:")
    stats = load_transport(g)
    for k, v in stats.items():
        print(f"  {k:28} {v:>6}")
    print(f"  -> {len(g):>7} triples total")

    OUTPUT_TTL.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=str(OUTPUT_TTL), format="turtle")
    print(f"\nSaved {len(g)} triples to {OUTPUT_TTL.relative_to(ROOT)}")
    return g


if __name__ == "__main__":
    main()

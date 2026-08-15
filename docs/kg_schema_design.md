# KG Schema Design

**Status: implemented.** This design is built — see `kg/schema/ontology.ttl`
(the formal TBox) and `kg/ingestion/build_kg.py` (the ABox instantiation, one
function per source below). This doc remains the reference for the *why*.

Covers the "KG Modelling" step: a unified data model for transport nodes, POIs,
categories, spatial relations, and temporal aspects, per the one-pager. Builds
directly on `docs/kg_modelling_decisions.md` (scope + cleaning decisions) and
`docs/wiener_linien_api_notes.md` (transport data shape).

## Vocabulary strategy

Reuse established vocabularies where a solid match exists, rather than inventing
everything from scratch — this is standard KG practice and directly relevant to
comparing data models across communities (schema.org from the search/e-commerce
world, W3C Geo from the early semantic web, SKOS from library/taxonomy science).
Custom terms only where nothing off-the-shelf fits well.

| Prefix | Namespace | Used for |
|---|---|---|
| `viennakg:` | `http://example.org/viennakg#` | project-specific classes/properties with no good existing match |
| `schema:` | `https://schema.org/` | POI types, names, addresses, contact info, amenities |
| `geo:` | `http://www.w3.org/2003/01/geo/wgs84_pos#` | coordinates (`geo:lat`, `geo:long`) |
| `skos:` | `http://www.w3.org/2004/02/skos/core#` | the Wien Tourismus category/subcategory taxonomy |
| `dcterms:` | `http://purl.org/dc/terms/` | provenance (`dcterms:source`, `dcterms:license`) |

`schema:Museum` and `schema:Library` were verified directly against schema.org's
type pages (both exist as `Thing > Place > CivicStructure > ...`). The others
(`Park`, `TouristAttraction`, `AdministrativeArea`, `amenityFeature`/
`LocationFeatureSpecification`, `containedInPlace`) are long-standing, stable
schema.org terms — worth a quick double-check against schema.org docs during KG
Creation if anything doesn't map as expected, but not re-verified one-by-one here.

## Class hierarchy

```
schema:Place
├── viennakg:POI                      (common supertype for all 7 POI sources)
│   ├── schema:Museum                 Museen
│   ├── schema:Library                Büchereien
│   ├── viennakg:BathingSite          Badestellen (custom — not all are "beaches")
│   ├── schema:Park                   Parkanlagen
│   ├── viennakg:SwimmingPool         Schwimmbäder (custom — no clean schema.org fit)
│   ├── viennakg:PlaygroundArea       Spielplätze — ONE PER ROW, not per named playground
│   └── schema:TouristAttraction      Sights (Sehenswürdigkeit, Schloss & Palais)
├── viennakg:Stop                     Wiener Linien stop (from haltestellen.csv)
├── viennakg:Platform                 Wiener Linien platform, carries RBL (from steige.csv)
└── (schema:AdministrativeArea)
    └── viennakg:District             Bezirk 1–23, promoted from a raw int to a real entity

viennakg:Line                         not a Place — a transit service/route
viennakg:Departure                    live: one scheduled/real-time departure at a Platform
viennakg:Disruption                   live: a time-bounded service disruption
viennakg:OccupancyStatus              live: Schwimmbad daily occupancy traffic-light
schema:LocationFeatureSpecification   reused: named boolean/valued feature of a place
skos:Concept                          category/subcategory taxonomy nodes
```

### Why `viennakg:District` instead of a plain `BEZIRK` integer

Every POI file used a raw `BEZIRK` integer (or, for Wien Tourismus, a derived one
from `POSTALCODE`). Modelling district as its own class rather than a literal
means district-level queries ("everything in Donaustadt") and future reasoning
("prefer POIs in the same or an adjacent district") have something to actually
reason over, instead of just filtering on equal integers. 23 named individuals
(`viennakg:Bezirk1` … `viennakg:Bezirk23`), linked from POIs via
`schema:containedInPlace`.

### Why `viennakg:PlaygroundArea` is one node per CSV row, not per named playground

Per your call: separate nodes per feature. `SPIELPLATZPUNKTOGD.csv` already has
one row per point-feature (each with its own coordinates), and the 137 "repeat"
names found in EDA are genuinely different sub-areas sharing a playground name —
so each row becomes its own `viennakg:PlaygroundArea` instance. Rows that share
a playground name are linked to each other only implicitly (same `schema:name`
value + same district) — no separate "parent playground" node is introduced,
since nothing in the source data actually names a distinct parent entity beyond
the repeated string.

## Key object properties

| Property | Domain → Range | Notes |
|---|---|---|
| `schema:containedInPlace` | POI/Platform/Stop → `viennakg:District` | reused schema.org property (confirmed on the Museum type page) |
| `viennakg:hasPlatform` | Stop → Platform | transport structure |
| `viennakg:servedByLine` | Platform → Line | transport structure |
| `viennakg:hasDeparture` | Platform → Departure | live |
| `viennakg:hasDisruption` | Stop or Line → Disruption | live |
| `viennakg:hasOccupancyStatus` | SwimmingPool → OccupancyStatus | live |
| `schema:amenityFeature` | POI → `schema:LocationFeatureSpecification` | **dual use, see below** |
| `viennakg:hasCategory` | POI → `skos:Concept` | category/subcategory tagging |
| `geo:lat` / `geo:long` | any spatially-located class → literal | standard W3C Geo vocab, applied directly to the resource |

### `amenityFeature` covers two different EDA findings with one pattern

Parks' clean `SPIELEN_IM_PARK`/`WASSER_IM_PARK`/`HUNDE_IM_PARK` Ja/Nein flags and
Spielplätze's free-text `SPIELPLATZ_DETAIL` equipment list look like different
problems in the raw CSVs, but both are really "does this place have feature X":
`schema:amenityFeature` → `schema:LocationFeatureSpecification(name=..., value=
true)` models both without inventing two separate patterns. Concretely: a Park
gets three `LocationFeatureSpecification` instances (Playground/Water/DogsAllowed
each true or false); a `PlaygroundArea` gets one `LocationFeatureSpecification`
per equipment item parsed out of its comma-separated `SPIELPLATZ_DETAIL` string.

## Per-file mapping (for KG Creation week)

| Source | KG class | Key fields → properties |
|---|---|---|
| `MUSEUMOGD_clean.csv` | `schema:Museum` | NAME→schema:name, BEZIRK→District, ADRESSE→schema:address, lon/lat→geo:long/lat, WEITERE_INF→schema:url |
| `BUECHEREIOGD.csv` | `schema:Library` | NAME, ADRESSE, BEZIRK, lon/lat, OEFFNUNGSZEITEN1-6→schema:openingHours (concatenated), TELEFON→schema:telephone, EMAIL→schema:email |
| `BADESTELLENOGD.csv` | `viennakg:BathingSite` | BEZEICHNUNG→schema:name, BEZIRK, lon/lat. `BADEQUALITAET`/`TYP` dropped per your call. `UNTERSUCHUNGSDATUM` optional, revisit for live layer |
| `PARKINFOOGD_clean.csv` | `schema:Park` | ANL_NAME, BEZIRK, lon/lat, FLAECHE_M2→viennakg:areaSqm, 3 Ja/Nein cols→amenityFeature |
| `SCHWIMMBADOGD.csv` | `viennakg:SwimmingPool` | NAME, ADRESSE, BEZIRK, lon/lat, AUSLASTUNG_*→OccupancyStatus (live, optional for first pass) |
| `SPIELPLATZPUNKTOGD.csv` | `viennakg:PlaygroundArea` | ANL_NAME→schema:name, BEZIRK, lon/lat, TYP_DETAIL→hasCategory, SPIELPLATZ_DETAIL (split on comma)→amenityFeature |
| `WIENTOURISMUS_sights_clean.csv` | `schema:TouristAttraction` | NAME, STREET→schema:address, BEZIRK (derived), lon/lat, SUBCATEGORY_NAME→hasCategory (skos:Concept) |
| `wienerlinien-ogd-haltestellen.csv` | `viennakg:Stop` | HALTESTELLEN_ID, NAME→schema:name, lon/lat, GEMEINDE |
| `wienerlinien-ogd-steige.csv` | `viennakg:Platform` | STEIG_ID, RBL_NUMMER→viennakg:rbl, FK_HALTESTELLEN_ID→hasPlatform (inverse), FK_LINIEN_ID→servedByLine |
| `wienerlinien-ogd-linien.csv` | `viennakg:Line` | LINIEN_ID, BEZEICHNUNG→schema:name, VERKEHRSMITTEL→viennakg:mode |
| `monitor` API (live) | `viennakg:Departure`, `viennakg:Disruption` | not ingested yet — Reasoning/Service Layer concern |

## SKOS category taxonomy

`viennakg:categoryScheme a skos:ConceptScheme`. One `skos:Concept` per
`CATEGORY_NAME` (e.g. "Sightseeing"), one per `SUBCATEGORY_NAME` (e.g.
"Sehenswürdigkeit", "Schloss & Palais"), linked with `skos:broader`
(subcategory → category). Currently only populated from the Wien Tourismus
source since that's the only file with an explicit category/subcategory split —
the other 6 POI types are each their own top-level category by construction
(their class already says what they are), so they get a single matching
`skos:Concept` each rather than a full taxonomy.

## Open items carried into KG Creation

- `viennakg:barrierFree` and live departure fields belong on `Departure`
  (from the `monitor` API response), not statically on `Platform` — the static
  `steige.csv` doesn't carry accessibility info itself.
- Opening hours and live occupancy/water-quality data are modelled but not
  wired into any reasoning logic yet — deliberate, per
  `docs/kg_modelling_decisions.md`.

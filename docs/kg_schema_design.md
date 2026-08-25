# KG Schema Design

Covers the "KG Modelling" step: a unified data model for transport nodes, POIs,
categories, spatial relations, and temporal aspects, per the one-pager. Builds
directly on `docs/kg_modelling_decisions.md` (scope + cleaning decisions) and
`docs/wiener_linien_api_notes.md` (transport data shape).

## Vocabulary strategy

Reused established vocabularies where a useful match existed.

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
`LocationFeatureSpecification`, `containedInPlace`) are not verified but sometimes were visible 
when browsing around.

## Class hierarchy

```
schema:Place
├── viennakg:POI                      (common supertype for all 7 POI sources)
│   ├── schema:Museum                 Museen
│   ├── schema:Library                Büchereien
│   ├── viennakg:BathingSite          Badestellen (custom, not all are "beaches")
│   ├── schema:Park                   Parkanlagen
│   ├── viennakg:SwimmingPool         Schwimmbäder (custom, no clean schema.org fit)
│   ├── viennakg:PlaygroundArea       Spielplätze, ONE PER ROW, not per named playground!!
│   └── schema:TouristAttraction      Sights (Sehenswürdigkeit, Schloss & Palais)
├── viennakg:Stop                     Wiener Linien stop (from haltestellen.csv)
├── viennakg:Platform                 Wiener Linien platform, carries RBL (from steige.csv)
└── (schema:AdministrativeArea)
    └── viennakg:District             Bezirke 1–23

viennakg:Line                         not a Place, a transit service/route
viennakg:Departure                    live: one scheduled/real-time departure at a Platform (to be implemented)
viennakg:Disruption                   live: a time-bounded service disruption               (to be implemented)
viennakg:OccupancyStatus              live: Schwimmbad daily occupancy traffic-light        (to be implemented)
schema:LocationFeatureSpecification   reused: named boolean/valued feature of a place
skos:Concept                          category/subcategory taxonomy nodes
```

### Why `viennakg:District` instead of a plain `BEZIRK` integer

Every POI file used a raw `BEZIRK` integer (or, for Wien Tourismus, from `POSTALCODE`). 
Modelling district as its own class rather than an integer means that actual queries 
("everything in Donaustadt") and potential reasoning ("prefer POIs in the same or an 
adjacent district") have something to actually reason over, instead of just filtering 
on integers.

### Why `viennakg:PlaygroundArea` is one node per CSV row, not per named playground
Essentially because it was easy.

## Key object properties

| Property | Domain > Range | Notes |
|---|---|---|
| `schema:containedInPlace` | POI/Platform/Stop > `viennakg:District` | reused schema.org property |
| `viennakg:hasPlatform` | Stop > Platform | transport structure |
| `viennakg:servedByLine` | Platform > Line | transport structure |
| `viennakg:hasDeparture` | Platform > Departure | live |
| `viennakg:hasDisruption` | Stop or Line > Disruption | live |
| `viennakg:hasOccupancyStatus` | SwimmingPool > OccupancyStatus | live |
| `schema:amenityFeature` | POI > `schema:LocationFeatureSpecification` | **dual use, see below** |
| `viennakg:hasCategory` | POI > `skos:Concept` | category/subcategory tagging |
| `geo:lat` / `geo:long` | any spatially-located class > literal | standard W3C Geo vocab, applied directly to the resource |

### `amenityFeature` covers two different EDA findings with one pattern

Parks' clean `SPIELEN_IM_PARK`/`WASSER_IM_PARK`/`HUNDE_IM_PARK` Ja/Nein flags
and Spielplätze's free-text `SPIELPLATZ_DETAIL` equipment list are really rather
"does this place have feature X": `schema:amenityFeature` > `schema:LocationFeatureSpecification
(name=..., value=true)` models.
E.g.: a Park gets three `LocationFeatureSpecification` instances
(Playground/Water/DogsAllowed, each true or false); a `PlaygroundArea` gets one
`LocationFeatureSpecification` per equipment item parsed out of its
comma-separated `SPIELPLATZ_DETAIL` string.

## Per-file mapping (for KG Creation week)

| Source | KG class | Key fields > properties |
|---|---|---|
| `MUSEUMOGD_clean.csv` | `schema:Museum` | NAME>schema:name, BEZIRK>District, ADRESSE>schema:address, lon/lat>geo:long/lat, WEITERE_INF>schema:url |
| `BUECHEREIOGD.csv` | `schema:Library` | NAME, ADRESSE, BEZIRK, lon/lat, OEFFNUNGSZEITEN1-6>schema:openingHours (concatenated), TELEFON>schema:telephone, EMAIL>schema:email |
| `BADESTELLENOGD.csv` | `viennakg:BathingSite` | BEZEICHNUNG>schema:name, BEZIRK, lon/lat. `BADEQUALITAET`/`TYP` dropped, see modelling decisions. |
| `PARKINFOOGD_clean.csv` | `schema:Park` | ANL_NAME, BEZIRK, lon/lat, FLAECHE_M2>viennakg:areaSqm, 3 Ja/Nein cols>amenityFeature |
| `SCHWIMMBADOGD.csv` | `viennakg:SwimmingPool` | NAME, ADRESSE, BEZIRK, lon/lat, AUSLASTUNG_*>OccupancyStatus (live, optional for first pass) |
| `SPIELPLATZPUNKTOGD.csv` | `viennakg:PlaygroundArea` | ANL_NAME>schema:name, BEZIRK, lon/lat, TYP_DETAIL>hasCategory, SPIELPLATZ_DETAIL (split on comma)>amenityFeature |
| `WIENTOURISMUS_sights_clean.csv` | `schema:TouristAttraction` | NAME, STREET>schema:address, BEZIRK (derived), lon/lat, SUBCATEGORY_NAME>hasCategory (skos:Concept) |
| `wienerlinien-ogd-haltestellen.csv` | `viennakg:Stop` | HALTESTELLEN_ID, NAME>schema:name, lon/lat, GEMEINDE |
| `wienerlinien-ogd-steige.csv` | `viennakg:Platform` | STEIG_ID, RBL_NUMMER>viennakg:rbl, FK_HALTESTELLEN_ID>hasPlatform (inverse), FK_LINIEN_ID>servedByLine |
| `wienerlinien-ogd-linien.csv` | `viennakg:Line` | LINIEN_ID, BEZEICHNUNG>schema:name, VERKEHRSMITTEL>viennakg:mode |
| `monitor` API (live) | `viennakg:Departure`, `viennakg:Disruption` | not ingested yet, now for POV historic data is sufficient |

## SKOS category taxonomy

`viennakg:categoryScheme a skos:ConceptScheme`. One `skos:Concept` per
`CATEGORY_NAME` (e.g. "Sightseeing"), one per `SUBCATEGORY_NAME` (e.g.
"Sehenswürdigkeit", "Schloss & Palais"), linked with `skos:broader`
(subcategory > category). Currently only populated from the Wien Tourismus
source since that's the only file with an explicit category/subcategory
split. The other 6 POI types are each their own top-level category by
what their class already says, so they get a single
matching `skos:Concept` each rather than a full taxonomy.
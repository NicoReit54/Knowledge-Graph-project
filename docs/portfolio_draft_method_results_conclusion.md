## 1. Introduction/Background

I wanted to work on something related to my surroundings. The City of Vienna
provides quite rich open data and since I grew up here, I dug into what was possible with what I have easily available. The existing resources naturally led me to focus on typical points of interest and how to connect this to (live) data provided by Wiener Linien.1
Problem. Sometimes it would be nice if somebody else planned a day or just a few hours of
activities for you. Doing this yourself you have to (obviously) consider your interests, time
constraints, travel times and such. This project I set up to integrate public information on the City of Vienna with (live) Wiener Linien data into a unified KG. It will model transport links, points-of-interests, categories, spatial proximity (and temporal (live) data). Reasoning techniques shall be used to generate personalized activity plans and/or route suggestions based on user interests and (live) mobility conditions/constraints.

In the third chapter you will see how this actually worked out and what I had to adapt to explore the topic of knowledge graphs and the various LOs with reasonable time and effort!

## 2. Method

The project is structured in a sort of pipeline with six steps(/notebooks that use methods/classes in .py scripts):
- Data Collection & EDA
- KG Modelling
- KG Creation
- Reasoning
- Service layer creation
- and last but not least a simple KG Evolution.

Each step builds on the previous one, and most have its own decisions log in the repo (`docs/*_decisions.md`) where I wrote down the explanation on the choices below in more detail. The following is essentially a summarized version of those including references to the respective LOs that I think are fulfilled by that particular part:

**Data & modelling**
As planned, I combined seven City of Vienna open data sources (museums, libraries, bathing sites, parks, swimming pools, playgrounds, tourist attractions) with Wiener Linien's static transit data (stops, platforms, lines) and its full GTFS schedule feed. The live data feed was left out for now simply due to time constraints. It should, however, not take much effort as the structure for the live API is the same as for the static data.

For the ontology (LO5) I reused known vocabularies wherever a reasonable match existed rather than inventing everything myself:
- schema.org for POI types, names, addresses and amenities,
- W3C Geo for coordinates,
- SKOS for the one taxonomy in the source data that has a two-level category/subcategory split since the one data set from "Wien Tourismus" was a bit differently structured than the others.

Everything without a good and easy to find existing match, mainly the transport-specific classes and some others own derived features, are caught with the special `viennakg:` namespace.

**KG Creation (LO7).**
I went with an in-memory `rdflib.Graph()` serialized to one Turtle file rather than setting up an external triple store. At this project's scale (80,485 triples for the base KG) that build finishes in a few seconds and needed no separate infrastructure to install or keep running, which mattered more for me to get the thing going to work on other LOs given I am doing this alongside a 30h job. One can always plug in the triple store at the end since the structure/queries/... are the same (#PlugAndPlay).

GTFS's trip-level data is the one part I kept out of the graph on purpose: a full day of data is still millions of rows, and tripling that would have overloaded the rest of the KG for no reasoning benefit. So, for the time being, it stays as it is and gets loaded by pandas instead. This is the sort of data-model trade-off LO4 might refer to: Using RDF triples for the content data (POIs, categories, districts) and a "plain table" for "supporting materials" (GTFS timetables).

**Reasoning (LO6).**
The main reasoning can be found in the preference-matching layer, find_pois(): category, amenity and district matching >> all done as SPARQL queries against the KG. Separately, I tested whether RDFS materialization (via owlrl) could make viennakg:POI directly queryable instead of listing its seven subclasses by hand: a full DeductiveClosure pass didn't finish within two minutes on this graph on my machine. Hence, a hard-coded list of the classes was used. In a real-life application however, it would not be too bad of a choice to query the subclasses initially before going online and keep them in-memory until something changes.

Travel time estimation itself, comes from a separate component: GtfsRouter, which is not knowledge-graph reasoning: it works over GTFS's tabular schedule data, kept outside the KG for the before-mentioned scale reasons in the Method/KG Creation section above, and just feeds a travel-time number into the Service Layer. It's a bounded, round-based reachability search loosely inspired by RAPTOR (round 0 direct, round 1 one transfer, round 2 two transfers, pandas-vectorized, roughly 0.2-0.4s per search). I built this with substantial help from Claude as I had no prior experience with the GTFS standard (really interesting to hear about its existence though!), and the routing algorithm specifically is one of the parts of this project where I leaned on AI assistance the most, as also noted in the Declaration.

**Service (LO9, LO11).**
find_pois() combines the category/amenity/district matching from KG Modelling with GtfsRouter's travel times to answer simple questions like "find me a park, with a playground, in the 6th district, ranked by how fast I can get there". It also includes a simple description assembled from whatever structured fields a POI actually has (there's no free-text description anywhere in the source data. However, this is for sure one of those things that could be easily expanded by an LLM (LO12) if time was no issue).

On top of that, plan_activities() builds the multi-stop itineraries, up to five stops, in the order given. I used a bounded beam search rather than exhaustive branching (or any other sophisticated algorithm) here: full branching costs grow with the number of candidates raised to the number of stops, which is minutes of runtime for five stops, while beam search keeps only the best beam_width (e.g. 3) partial itineraries after each stage. This bounds the cost to roughly `beam_width x stops` route searches instead (it oscillates between that and beam_width^2 x stops, just imagine using three branches, there three each again. So, nine at this point, and then choosing the three shortest paths of those, so back to three again and so on). It's heuristic, so it is not guaranteed to find the globally best one, but it's good enough for now and could be exchanged if wanted. I also did not search over stop orderings (that would be a sort of travelling-salesman problem on top of the beam search, multiplying cost by up to 5! for five stops) and instead visit stops in exactly the order given (the user can also simply exchange those).

**KG Evolution (LO8).**
Last but not least I added a simple rule-based evolution demonstration in `kg/enrichment/infer_tags.py`, which can be run once after the KG is built. It adds facts that no source file states directly, derived from triples already in the graph, e.g. tagging a park as "family friendly" when it has both a playground and a water feature amenity, or a tourist attraction as an "old town landmark" purely from being located in the first district. Of course there could be much more sophisiticated approaches, but this is purely a demonstration of what is possible even with minor inputs!

Further, I gave these their own predicate (viennakg:inferredTag) rather than mixing them into the sourced amenity data, so we can query for this inferred data specifically.

## 3. Results

The base KG consists of 80,485 triples across all seven POI sources plus the transport structure; the KG evolution step adds 2,035 more (82,520 total). All five stages from Data Collection through the Service Layer have a working initial POC version, each captured in a separate notebook.

A few concrete numbers/facts: The routing engine resolves a full network reachability search from one origin in roughly 0.2-0.4 seconds on a MacBook Air M1, fast enough to rank POI categories fairly interactively (see notebooks/06_service_layer.ipynb). The multi-stop planner's beam search scales fairly linearly with beam_width: On my machine, a five-stop plan takes about 18 seconds at beam_width=2; 26 at 3; 34 at the default of 4; and 50+ at 6, all well under a comprehensive branching alternative (setting the branching to e.g. 99), which I never actually let finish since it took so long.

On the KG Evolution side, the five completion rules matched 465 of 1,051 parks as family-friendly, 491 of 771 playgrounds as above-averagely equipped, 313 of 1,051 parks as quiet pocket parks, 87 of 247 tourist attractions as old-town landmarks, and 679 of 771 playgrounds as within a short walk of a transit stop. A nice funfact: That last rule's match rate (88%) is much higher than the other four, which most likely reflects how dense Vienna's own transit network is. I kept it anyway because (a) it is an interesting outcome and (b) it is the only one of the five rules that reasons across both the POI and the transit side of the graph rather than staying within one.

Compared to what I originally committed to in the one-pager, I did not get to LO3 (GNNs). It was on my list for basic proficiency, but between the personal time constraints and the Reasoning and Service Layers turning out to need more real design work than I had expected, I decided to leave it out. Everything else planned for basic proficiency or focus level has working code behind it, as shown already.

The things I also left out of scope but that are not impacting whether or not I touched an LO: live data from the Wiener Linien monitor API (as it should be fairly easy to plug in any way), a return trip home in the generated itineraries (only at the end I realized that it would be fairly useful in a real working version), and aligning the stop orderings in the multi-stop planner to create an efficient itinerary. None of these are blockers really, they should be fairly simple additions that do not break the logic or would need major changes on how the current code functions already.

## 4. Conclusion

Coming back to the problem from the first chapter: I wanted something that could take my interests, my time budget and actual travel times and turn that into a plan I did not have to piece together myself. That is what this project ended up doing, not as a polished product, but as a working pipeline where every step, from the seven raw CSVs to a five-stop itinerary with a real ranked description, actually runs on real data rather than staying a diagram in a decisions log.

If I look back at the six steps, most of what I set out to do in the one-pager has working code behind it, not just a plan for it: the ontology reuses established vocabularies instead of me inventing my own from scratch (LO5), the KG itself is a real 80,485-triple graph rather than a handful of demo triples (LO7), reasoning happens as actual SPARQL over that graph with a documented scalability limit rather than an unqualified claim that "it scales" (LO6), the Service Layer answers real preference + travel-time questions and chains them into multi-stop plans (LO9, LO11), and the KG Evolution step shows the graph can grow facts on its own after the fact, not just at ingestion time (LO8). LO3 is the one clear gap against the plan, and I would rather say that plainly here than dress it up as intentional scope-cutting from day one, it was a real tradeoff made partway through once it became clear the Reasoning and Service Layers needed more of my time than I had budgeted for.

Some of what I built leaned more on Claude than other parts, and I think that split is itself informative: the KG design, the ontology choices, the SPARQL logic and the KG Evolution rules are things I understood and made the calls on myself, using Claude mostly to harden and clean up what I had already decided. GtfsRouter is the clear exception, GTFS was new to me entirely, and that component would have taken me considerably longer to get right without that help. I do not think that is a weakness of the project so much as an honest account of where my own knowledge going in was strong versus where it wasn't.

If I kept working on this past the deadline, the three things flagged in the Results section are exactly where I would start: plugging in live data (the static structure already matches the live API), adding a return trip so a plan actually gets you home, and letting the planner reorder stops instead of just accepting whatever order they were given in. None of those change the underlying KG or reasoning, they are refinements on the Service Layer sitting on top of what already works. LO3 would be the other obvious next step, and honestly a better one to attempt now than earlier in the project, given there is now a stable KG and a working Service Layer to actually build embeddings or a GNN against, instead of guessing what such a component would even need to plug into.

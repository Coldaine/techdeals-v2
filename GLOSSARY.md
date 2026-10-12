
# TechDeals v2

Canonical vocabulary for the TechDeals v2 rebuild. The domain is used
hardware and datacenter gear — sources sell or auction it, the pipeline
decomposes it into items, prices it over time, and makes it answerable.
These definitions are the language every mission, review, and document uses.

## Language

### Evidence and provenance

**Capture**:
A single fetch of a source: the raw page payload plus where and when it was
fetched. The only input the pipeline accepts.
_Avoid_: scrape, page, download

**Posting**:
The atomic unit of evidence — one capture, whatever it contains: one item, a
configured server, a lot, or a wanted post. Postings are never edited, merged,
or deleted; they are only added.
_Avoid_: listing, product, item (an item is a Line)

**Provenance**:
The where-seen/when-seen facts attached to every capture: source, URL, fetch
time, and a content checksum. Nothing enters the system without it.

**Offer Key**:
The stable identity of an offer, derived from its natural facts so that
re-parsing the same capture never invents a second offer.
_Avoid_: offer id, dedupe key

**Extraction**:
One parse pass over one capture. Re-running a parser produces a new
extraction; it never rewrites the old one.
_Avoid_: parse job, ingest run

**Batch**:
Many postings parsed together in a single LLM call. Batched parsing is a
requirement, never an optimization; one-listing-per-call is a defect.
_Avoid_: single parse

### Decomposition

**Line**:
One item decomposed out of a posting, carrying the seller's stated
description and stated quantity. Lines can nest: components inside a server
line, manifest rows inside a lot line.
_Avoid_: product, SKU, item row

**Stated Quantity**:
How many units of a line the seller says are present, as stated — not
inferred or rounded.

**Separately Purchasable**:
Whether a line can be bought on its own, or only as part of a larger purchase.

**Sale Group**:
The set of lines that can actually be bought together in one purchase — a
configured server as one unit, each DIMM bought individually, a whole lot.
Alternative purchase shapes of the same posting are distinct sale groups.
_Avoid_: bundle, package, offer (see Offer)

**Membership Terms**:
Which lines are in a sale group and how many of each one's stated quantity
the purchase includes.

### Prices and time

**Offer**:
Something purchasable at a price — a line or a sale group, at a point in
time. Observations attach to offers.
_Avoid_: posting (a posting is evidence; an offer is what is for sale)

**Price Kind**:
Which market fact a price is — these series are never conflated:
- **Ask** — what a seller is asking
- **Bid** — what a buyer has offered (auction)
- **Sold** — a completed transaction
- **Cost Basis** — what we paid internally, not a market price
- **Reference** — a third-party or list price used for comparison

**Price Basis**:
How a price amount relates to units — the honesty record:
- **Explicit Unit** — the price was stated per unit
- **Homogeneous Division** — a lot total divided across identical units
- **Bound-Only** — only bounds are known; never allocate to units
- **Allocated** — a lot total apportioned across different components, with
  the basis recorded

**Availability**:
Whether an offer is currently purchasable — a time series alongside price.

**Observation**:
An appended price or availability event. Observations are never updated or
deleted; corrections point to a superseding observation.
_Avoid_: price update, correction row

### Identity

**Resolution**:
A candidate product match for a line, with a confidence score. Resolutions
are re-runnable and never block anything from being visible; unresolved
postings appear in every read view immediately.
_Avoid_: identity merge, dedupe, match lock

**Product**:
The canonical identity lines resolve to. Never trusted implicitly — always
arrived at through scored resolutions.
_Avoid_: item, SKU

**Category**:
A named spec, built dynamically by adding data — not by changing the schema.
_Avoid_: type, taxonomy node

### Honesty

**Quarantine**:
An explicit, visible exclusion state with a reason (out-of-scope item, wanted
post, parse failure). Quarantined things are counted, never silently dropped.
_Avoid_: skip, filter, delete

**Wanted Post**:
A post seeking to buy, not to sell. Excluded from inventory with a recorded
reason; never treated as an ask.

**Parse Failure**:
An extraction that could not complete. The capture's payload stays intact
for re-extraction; the failure is visible, not hidden.

**Coverage**:
The fraction of captures that reach a queryable state — extracted, priced,
resolved or explicitly unresolved. Drops and quarantines count as long as
they are visible with reasons.

**Trust**:
The guarantee that query answers are correctly decomposed, priced, and
kinned: zero fabricated unit prices, zero conflated price kinds.

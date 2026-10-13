# TechDeals v2

Words for used hardware and datacenter gear. A source sells or auctions it, the pipeline breaks a listing into parts, prices those parts over time, and answers questions about them.

The format of this file is not fixed. The domain-modeling skill is optional. It does not get to ban a word the owner uses.

## Listing

A listing is one capture: the raw payload plus where and when it was fetched. It may be one part, a configured server, a lot, or a wanted post. Listings are only added. They are not edited, merged, or deleted.

Posting is the same thing. It is the name used in the schema. It is not a second object.

A capture is that fetch. Provenance is the source, the URL, the fetch time, and a content checksum. Nothing enters without those.

An extraction is one parse of one listing. A new parse adds an extraction. It does not rewrite the old one. A batch is many listings parsed in one model call. One listing per call is a defect.

The offer key is the stable identity of an offer, taken from its natural facts, so parsing the same listing again does not invent a second offer.

## Parts

A line is one part taken out of a listing, with the seller's stated description and stated quantity. Lines can nest: parts inside a server, rows inside a lot. Stated quantity is what the seller said, not a guess. Separately purchasable means the line can be bought alone.

A sale group is the set of lines that can be bought together in one purchase: the whole server, each DIMM alone, or the whole lot. Two ways of buying the same listing are two sale groups. Membership terms say which lines are in the group and how many of each stated quantity the purchase includes.

## Price

An offer is a line or a sale group that can be bought at a price. A listing is the evidence. An offer is what is for sale.

An observation is one appended price or availability event. Observations are not edited. A correction points at a later observation.

Price kind is which fact the number is. These stay separate: ask, bid, sold, cost basis, and reference. A reference is a third-party or list price used for comparison. It is a kind of price, not a role.

Price basis is how the amount relates to units: explicit unit, homogeneous division of a lot of identical units, bound-only (bounds known, nothing allocated), or allocated across different parts with the basis recorded.

Availability is whether the offer can be bought, recorded over time next to price.

## Analysis

A comp is a role, not a thing in the database. During an analysis, a listing used to price another listing is a comp. When the analysis is over, it is a listing again. A comp is not the Reference price kind.

## Identity

A resolution is a candidate product match for a line, with a confidence score. It can be run again. An unresolved listing stays visible.

A product is the identity a line resolves to. It is reached through resolutions. It is not trusted just because a row exists.

A category is a named spec, added as data.

## Honesty

Quarantine is a visible exclusion with a reason: out of scope, a wanted post, or a parse failure. Those rows are counted.

A wanted post is someone trying to buy. It is not an ask.

A parse failure keeps the payload for another extraction. The failure stays visible.

Coverage is the share of captures that reach a queryable state, including the ones that were quarantined, as long as the reason is visible.

Trust means the answers are decomposed, priced, and kinded without invented unit prices and without mixing price kinds.

# Source collection: refurb servers and hardware price research

Status: proposed execution plan; no new collectors or schedules deployed.

## Scope and authority

Cover every source in [TechdealsHandoff issue #226](https://github.com/MooseGooseConsulting/TechdealsHandoff/issues/226) and the [price-source hierarchy](https://github.com/MooseGooseConsulting/TechdealsHandoff/blob/main/docs/research/pc-price-source-hierarchy.md). Source usefulness means the evidence it contributes, not whether an existing scraper works. The issue's October 6 site checks are historical evidence, not proof of today's acquisition route.

The deliverable is an accumulating, queryable corpus of source listings, stated attributes, contents, prices, and dates. Collection does not decide comparability or whether to buy. Discovery pages, specifications, and historical prices remain useful evidence even without a current merchant ask.

This plan extends acquisition planning; it does not authorize production changes, paid requests, credential bypasses, or bulk browser crawling. BRIEF.md keeps the existing collectors where they run. Inspect existing acquisition logic before implementing anything new. If v2 needs live capture, use a thin fresh fetcher and its current capture intake; do not copy legacy identities, writers, or scraper infrastructure into v2. Keep the production cluster unchanged.

## Work order

1. **Source reconnaissance.** For each inventory row, record a real entry URL, supported product scope, public price examples, terms/access restrictions, pagination shape, route, and blocker if any. Try public structured data/feed/direct HTTP first. These routes are candidates until exercised; do not assume Shopify or an API from a storefront name.
2. **End-to-end pilot.** Start with UnixSurplus as the baseline, The Server Store, TechMikeNY, PC Server and Parts, ServerMall, and TechBuyer. In parallel scope the hierarchy's component-deal surfaces: r/buildapcsales, SlickDeals, DealNews, Woot, Newegg Daily Deals, and Google Shopping's permitted manual intake. Each pilot must fetch actual evidence, retain it, parse representative shapes, and read the stated fields back from the scratch corpus. No source is covered merely because its adapter exists.
3. **Complete both inventories.** Work through the remaining US/EU resellers, borderline candidates, editorial/reference pages, and history providers. Give every source an acquired result or a precise unresolved access/scope blocker. Do not silently omit low-priority sources.
4. **Repeat and broaden.** Repeat successful pilots on distinct collection dates; then traverse their explicitly scoped categories/searches. Measure discovered, fetched, stored, parsed, unresolved, and failed records separately. Record what lies outside the traversal; never call a bounded search a full catalog.
5. **Schedule only proven routes.** Propose schedules in the owning runtime repository through separate reviewed PRs. Suggested starting cadence: daily scoped server catalogs; more frequent flash-deal feeds; weekly/on-demand specifications; history lookup on demand. These are proposals, not active schedules or freshness guarantees. Verify a scheduled run and corpus readback before declaring it live.

A complete slice ships acquisition plus intake plus query proof, not an unconnected scraper. Source slices can run independently after the pilot establishes the capture contract. Group implementations only when inspected sources actually share a transport/shape.

## Refurb server inventory

Issue #226 contains 26 Tier-1 domains, a separate baseline, and five borderline entries. TechBuyer US is a regional route on the same source, not a second merchant. Preserve the route because currency, shipping, tax, and stock may differ.

| Source | Evidence sought | Execution order |
|---|---|---|
| unixsurplus.com | Baseline used-server configurations and asks | Pilot |
| theserverstore.com | Complete servers and separately labeled barebones | Pilot |
| techmikeny.com | Configured used servers and options | Pilot |
| pcserverandparts.com | AMD EPYC configurations, stock, warranty | Pilot |
| servermall.com | Milan-capable servers, currency, shipping/warranty terms | Pilot |
| techbuyer.com | Used configurations and regional terms | Pilot |
| savemyserver.com | Configured servers; Server Design Lab is its brand, not another source | Expand US |
| servermonkey.com | Refurbished server configurations and asks | Expand US |
| newserverlife.com | Dell/HPE configurations including EPYC platforms | Expand US |
| natex.us | Barebones and servers, clearly distinguished | Expand US |
| stikc.com | Refurbished Dell configurations | Expand US |
| tekboost.com | Configured Dell/HPE and warranty terms | Expand US |
| enterasource.com | Priced configurable servers | Expand US |
| networktigers.com | Dell/Cisco complete systems versus parts | Expand US |
| dellrefurbished.com | Off-lease systems with explicit server scope | Expand US |
| aventissystems.com | Refurbished server configurations | Expand US |
| itcreations.com | Server configurations and component descriptions | Expand US |
| xbyte.com | Dell configurations | Expand US |
| altatechnologies.com | Priced complete-server scope versus quote-only pages | Expand US |
| exittechnologies.com | Public complete-server scope versus other inventory | Expand US |
| worlddataproducts.com | Public complete-server prices versus quotes | Expand US |
| wiredzone.com | Supermicro configurations; distinguish new/refurbished | Expand US |
| cloudninjas.com | Refurbished server configurations | Expand US |
| bargainhardware.co.uk | Configurations, VAT/currency and shipment terms | Expand EU |
| etb-tech.com | Configurations, VAT/currency and shipment terms | Expand EU |
| servershop24.de | EUR server configurations and shipment terms | Expand EU |
| serverando.de | EUR server configurations and shipment terms | Expand EU |
| store.flagshiptech.com | Verify public asks versus quote/build-to-order | Borderline verification |
| techbuyer.com/us/ | Verify regional stock and US pricing separately | Borderline route verification |
| intelligentservers.co.uk | Verify current domain/rebrand and complete systems | Borderline verification |
| itinstock.com | Verify complete systems versus components | Borderline verification |
| dedicatednetworksinc.com | Verify server inventory versus networking-only scope | Borderline verification |

The first buying scope is 2P Milan-capable Supermicro H12, Dell R7525, and HPE DL385 Gen10+ listings. Platform capability is not proof of installed CPUs. Retain other captured configurations without falsely labeling them as 2P Milan. Record CPU model/count, installed RAM versus supported maximum, stated module counts/sizes, storage, chassis, controllers, PSUs, condition, availability, location, warranty, ask, currency, and shipping/tax when stated. Missing fields stay unknown. Preserve option-specific prices and default configurations; never combine a base ask with an upgraded specification.

## Price-source hierarchy inventory

| Source | Useful contribution | Acquisition pilot / gate |
|---|---|---|
| r/buildapcsales | Component flash-deal reports and merchant links | Permitted official API/feed; verify current access, retain post and destination separately |
| r/LaptopDeals | Laptop deal reports; occasional relevant leads | Same access check; store out-of-scope records without promoting them as tracked hardware |
| SlickDeals | Deal reports, coupon conditions, merchant links | Existing RSS logic first; broaden beyond the current mini-PC query with explicit searches |
| DealNews | Used/refurbished and component deal reports | Public category/article fetch, then cited merchant page |
| Woot | Refurbished/open-box hardware offers | Public computers category and product captures; preserve expiry/condition |
| Tom's Hardware Deals | Editorial reports and linked offers | Dated article capture plus distinct destination capture |
| LaptopMedia | Model/specification discovery | Scoped rankings/model pages; not a current offer merely because a model is recommended |
| TechBargains | Component deal discovery | Public category/article capture and merchant links |
| BensBargains | Community/editorial deal discovery | Public deal pages, stated dates/conditions and merchant links |
| Newegg Daily Deals | Retail asks and flash-sale terms | Public structured/direct route first; seller and option-specific price retained |
| PCMag Deals | Editorial roundups and linked offers | Article dates and individual citations; do not stamp old prices as fresh |
| Pangoly | Spec-filtered models and any attributed retailer price claims | Scoped public filter pages; retain claim provenance, do not treat MSRP as a buying benchmark |
| CamelCamelCamel | Amazon price history | Permitted product-history route; preserve price type and original historical timestamps |
| Keepa | Amazon price/availability history | Check licensed API access, cost and permission first; no paid calls without authorization |
| RTINGS.com | Reviews, measurements, model identification | Scoped public model pages; specifications/reviews are evidence, not fabricated asks |
| PCPartPicker | Multi-retailer prices and model matching leads | Public permitted access first; record restrictions if blocked, no challenge bypass |
| Google Shopping | Merchant discovery and attributed price reports | Existing manual CSV/paste route; automation needs a separately approved permitted route |

A deal report is evidence in its own right, not garbage until its destination can be fetched. Link it to the destination while retaining both observations and their dates. Multiple articles citing one merchant offer are not independent price samples. MSRP, historical prices, bids, asks, sold amounts, and cost basis remain distinct; downstream analysis chooses which to compare.

The hierarchy also names DiskPrices, r/homelabsales, and r/hardwareswap as existing coverage. They are continuity inputs, not omitted sources: verify representative retained captures can enter the new intake without changing their live collectors. Do not infer failed collection from Reddit's deliberately partial rolling-window status.

## Evidence and completion gates

For each source, the implementation PR must include:

- Real fetched/imported evidence with source URL/native key where available, receipt/fetch time, source observation/publication time when stated, retained payload and checksum. A page's last-update date is not its fetch date or necessarily its price observation date.
- Durable intake for every acquired record before price, product identity, or extraction succeeds. Partial/error records remain retrievable; unsupported source fields stay in raw evidence.
- Query readback of actual titles, stated amounts/currencies, price kinds, units/quantities, configuration or child lines, availability, condition, and time. Missing shipping does not mean free shipping; EUR and USD are not pooled without an explicit conversion analysis.
- A second-date collection showing price/availability history when a source changes, and replay without duplicate logical intake. No invented changes if the page is unchanged.
- Representative edge coverage: barebones versus configured server, base versus selected options, several component rows, lot versus each-price, foreign currency, unavailable listing, expired article/coupon, and a no-price specification page. Use actual source shapes, not invented rows to claim source coverage.
- Scoped pagination/accounting, rate-limit behavior, route cost and access restrictions. Browser use is targeted only after supported cheap routes fail for a genuine rendering need. Authentication/policy denial is a blocker, not permission to bypass or escalate to paid scraping.
- Independent review before merging. Record remaining blockers accurately; issue closure requires all assigned sources covered or explicitly deferred by the owner.

Do not use this acquisition rollout to approve pricing assumptions. [v2 issue #2](https://github.com/Coldaine/techdeals-v2/issues/2) remains the empirical review of capacity matching, DDR4 pooling, count/spread rules, currency and unavailable-price usage after richer evidence is collected. No family-rate or deal-score decision is hidden inside an adapter.

## Tracking and cutover

Use this PR as the inventory baseline. Open implementation issues per inspected shared route or source slice, linking source rows and the gates above. Keep #226 as the upstream server-source request; link progress there rather than closing it on a plan. Link the hierarchy's original source document in every applicable slice.

Neither this plan nor a collector PR replaces the live system. Run the new corpus independently, prove queryable multi-source evidence, and propose a separate reviewed cutover only after ingestion and history work. Retire old writers only after their successor is verified; do not join legacy product identities into the new price corpus as truth.

# Listing sources for a public Apartment Hunter

Researched September 25, 2026. No live listing searches, paid API calls, account registrations, purchases, or partner outreach were performed. StreetEasy and Zillow remain enabled. This is a source assessment, not a claim that any integration is already available.

## Recommendation

Use **RentCast for a small structured-data pilot** and investigate **REBNY RLS licensing for a full NYC product with listing media**. A different consumer website alone does not establish reliable access or permission to publish its listings. Keep browser capture a local, explicitly initiated feature while evaluating licensed feeds.

| Candidate | Access and publishing | Fit for this app | Decision |
| --- | --- | --- | --- |
| RentCast | Documented API; its API license expressly permits display and distribution subject to its other terms. Self-service key; 50 free requests/month for evaluation. | Active rentals, coordinates, rents, beds, baths and size. Published schema lacks photos, descriptions, availability dates and a native listing-page URL. | Best first data pilot, but not a complete replacement for photo scoring and click-through links. |
| REBNY Residential Listing Service | Licensed feeds via Trestle/RESO. Brokerage/member routes and a separate syndication-partner application. Fees and approval apply. | NYC sale and rental inventory; better candidate for a consumer listings product. Media rights, AI analysis rights and actual available fields must be confirmed in the agreement. | Best longer-term route to investigate. Not an anonymous public API. |
| Direct owners/property managers | A negotiated feed or export with explicit display/media permission. No universal source or agreement verified here. | Potentially fresh unit-level availability and photos; coverage depends on partnerships. | Useful supplement, not a complete NYC inventory by itself. |
| RentHop | Terms prohibit automated access and unapproved commercial/third-party use. | Another NYC consumer source, but changing portals does not solve access or redistribution. | Do not add a scraper; obtain a partner agreement first. |
| Zumper / PadMapper | Zumper prohibits collecting site content with crawlers/scrapers. Its published feed-partner route is for sending inventory **to Zumper**. | No documented outbound inventory license established by this research. | Ask about an outbound license if pursuing a partnership. |
| Apartments.com | Terms prohibit automatic copying/monitoring. Published feed docs cover uploading inventory and photos to the network. | An inbound syndication integration is not an API to fetch their whole inventory. | Do not use its consumer site as a scraping fallback. |
| Listings Project | Terms expressly restrict scraping, republication, caching and AI uses without permission. | Curated inventory may be useful to browse personally, but no integration permission established. | Keep outside automated ingestion. |
| NYC Housing Connect | Affordable-housing lotteries with household/income requirements and potentially months of waiting. | A different housing workflow, not an immediate market-rate rental substitute. No supported listings API established here. | Consider separately only if the product expands to affordable housing. |

## Evidence and remaining questions

- **RentCast access and cost:** [official getting-started article](https://help.rentcast.io/en/articles/7992900-rentcast-property-data-api). The free tier is 50 requests/month; verify paid pricing in the account dashboard before choosing a plan.
- **RentCast inventory:** [property listings docs](https://developers.rentcast.io/reference/property-listings) describe active/inactive rentals, geographic queries and pagination up to 500 records. RentCast says each listing is updated at least daily and new listings typically arrive within 12–24 hours. Its national coverage claims do not prove Manhattan apartment-unit completeness; that needs a future authorized pilot.
- **RentCast fields:** [published schema](https://developers.rentcast.io/reference/property-listings-schema) lists agent/office websites, which should not be mistaken for actual listing-page URLs. The media/description gaps above are observations from this schema. Confirm whether a separate product supplies them; never fabricate missing values or obtain missing photos by automatically opening another portal.
- **RentCast license:** [API terms, sections 1–2](https://www.rentcast.io/terms-api) permit use/storage and third-party display/distribution, with restrictions including key sharing and using its data to send automated queries to websites. A hosted app should retain its key server-side.
- **REBNY:** [technical solutions and syndication application](https://www.rebny.com/rls-technical-solutions/) and [RLS FAQs](https://www.rebny.com/rls-faqs/) distinguish IDX, VOW, product and back-office uses. Public display through a member feed entails licensing and potentially compliance review; back-office data is not for consumer display. Syndication partnership requires review and an agreement. Obtain current eligibility, costs, rental coverage, media permissions, attribution, retention/deletion rules and AI-scoring permission before implementation.
- **Portal restrictions:** [RentHop terms](https://www.renthop.com/resources/terms), [Zumper terms](https://www.zumper.com/terms-and-conditions), [Zumper feed policy](https://help.zumper.com/hc/en-us/articles/4404420570523-What-is-Zumper-s-policy-towards-feed-partners), [Apartments.com terms](https://www.apartments.com/grow/about/terms-of-service), [Apartments.com feed FAQ](https://www.apartments.com/grow/faq), [Listings Project terms](https://www.listingsproject.com/terms-of-use).
- **Affordable housing:** [NYC's Housing Connect overview](https://access.nyc.gov/programs/nyc-housing-connect/) explains household/income eligibility and timelines. This assessment does not infer the user's eligibility.

## Next integration, once a source is chosen

1. Benchmark licensed sample results against the existing saved listings for NYC unit coverage, duplicate units, fresh prices and useful destination links. Report unknown data rather than guessing it.
2. Add a separate API source adapter with provider limits, pagination, cache timestamps and offline fixtures. Browser safety limits continue to apply to browser sources.
3. Preserve provenance and distinguish unit records from building-level records. Skip photo scoring when no permitted media is supplied; do not silently promote a proxy or estimate to a fact.
4. Before hosting for other people, add per-user settings/data separation and usage limits. The current loopback server, personal Chrome and shared model keys are a local architecture; it has not been converted into a hosted service by this change.

## Browser safeguards implemented now

- Reuse an identical successful search capture for ten minutes, including across restarts; cached records do not refresh `last_seen` or overwrite newer data.
- Persist a minimum fifteen-minute cooldown after a human check (even if completed), or a 403/429 on the main document or a captured listing response. Honor a longer `Retry-After`.
- A completed check permits reading that current page. Further loads wait for a later user-initiated action; the tool does not schedule a retry.
- Retain minimum 20-second search and 30-second detail pauses, and record attempted loads before navigation so a crash cannot erase the pause.
- No fingerprint/user-agent changes, cookie resets, proxies, challenge solving or new listing-site requests. These changes reduce unnecessary traffic; they cannot guarantee freedom from bot checks or provide a publication license.

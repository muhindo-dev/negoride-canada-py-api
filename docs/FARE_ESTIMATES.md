# Typical fare estimates

The trip preview shows a guide for the rider's opening offer. Car hire remains a negotiated service: the estimate is not a fixed quote and does not change the amount both sides agree to.

## How the estimate is built

1. Read the driving distance and duration from the cached Google Routes result. A queued route refresh warms this cache. Until it is ready, use the existing road-distance and speed estimate.
2. Calculate a market baseline from the editable starting fare, rate per kilometre, and rate per driving minute.
3. Apply the selected service multiplier (car, courier, movers, airport, or special car), then respect the configured minimum fare.
4. When at least three completed negotiations exist within 20% of the same straight-line distance and for the same service, blend their 25th, 50th, and 75th percentiles into the estimate. Historical fares supply at most 70% of the result.
5. Show the typical range using the configured percentage spread. All amounts are integer CAD cents.

The range is advisory. Drivers and riders can still negotiate, and the accepted offer remains the agreed fare.

## Admin settings

Open **Admin → Settings → Fees & commission → Pricing**. The estimate settings are editable and audited with the rest of app settings:

- `pricing.fair_base_cents`: $4.25 starting benchmark.
- `pricing.fair_per_km_cents`: $1.75 per kilometre.
- `pricing.fair_per_min_cents`: $0.15 per estimated driving minute.
- `pricing.fair_spread_pct`: default 13% around the typical estimate.
- `pricing.fair_car_pct`, `pricing.fair_courier_pct`, `pricing.fair_movers_pct`, `pricing.fair_airport_pct`, `pricing.fair_special_car_pct`: service multipliers.
- `pricing.min_fare_cents`: existing minimum opening offer / estimate floor.

Defaults are an editable **Toronto starting point**, not a Canada-wide regulated tariff. Toronto’s current taxi information says meters start at $4.25. The City’s 2024 industry review describes the tariff components as $0.25 per 143 metres and $0.25 per 29 seconds of waiting (the report says those rates were last updated in 2022). The distance rate is about $1.75/km. The estimate's $0.15/minute is a modest driving-time contribution; the taxi waiting charge applies to stopped/slow periods and should not be treated as the price of every minute spent driving. Service multipliers are configurable planning defaults, not official city rates.

For another city or province, update the starting fare, distance/time rates, service multipliers, minimum, and spread before relying on the estimate. Airport charges are not added automatically because airport fees vary by airport and trip direction.

References:

- [City of Toronto: Taxis and Limousines](https://www.toronto.ca/city-government/public-notices-bylaws/bylaw-enforcement/taxis-and-limousines/)
- [City of Toronto: 2024 Review of the Vehicle-for-Hire By-law and Industry, section 6](https://www.toronto.ca/legdocs/mmis/2024/ex/bgrd/backgroundfile-251312.pdf)

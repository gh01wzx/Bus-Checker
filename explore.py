import requests
import os
import config
import statistics
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

URL = config.TRIP_UPDATES_URL
SUB_KEY = os.environ["AT_SUB_KEY"]
MAX_DELAY = 15 * 60

raw_resp = requests.get(URL, headers={"Ocp-Apim-Subscription-Key": SUB_KEY})

if raw_resp.status_code != 200:
    print(f"Request failed with status {raw_resp.status_code}")
    print(raw_resp.text[:300])
    raise SystemExit(1)

data = raw_resp.json()
entities = data["response"]["entity"]

print("Number of trips:", len(entities))

rows = []
for trip in entities:
    tu = trip["trip_update"]
    delay = tu.get("delay")

    if delay is None or abs(delay) > MAX_DELAY:  # filter out dirty ones
        continue

    rows.append(
        {
            "route_id": tu["trip"]["route_id"],
            "delay": delay,
        }
    )


by_route = defaultdict(list)

for row in rows:
    by_route[row["route_id"]].append(row["delay"])

summary = []

for route_id, delays in by_route.items():
    avg_delay = sum(delays) / len(delays)
    summary.append(
        {
            "route_id": route_id,
            "avg_delay_sec": round(avg_delay, 2),
            "trip_count": len(delays),
        }
    )

summary.sort(key=lambda x: x["avg_delay_sec"], reverse=True)

ON_TIME_EARLY = -60
ON_TIME_LATE = 5 * 60

delays = [row["delay"] for row in rows]
on_time = [d for d in delays if ON_TIME_EARLY <= d <= ON_TIME_LATE]
on_time_rate = len(on_time) / len(delays)
all_routes_avg_delay = sum(delays) / len(delays)
all_routes_median_delay = statistics.median(delays)
early = [d for d in delays if d < ON_TIME_EARLY]
late = [d for d in delays if d > ON_TIME_LATE]

print(f"On time rate: {on_time_rate*100:.2f}%")
print(f"Average delays(whole netwrok): {all_routes_avg_delay:.2f} seconds")
print(f"Median delays(whole netwrok): {all_routes_median_delay} seconds")
print(f"Number of bus running early(whole netwrok): {len(early)}")
print(f"Number of bus running on time(whole netwrok): {len(on_time)}")
print(f"Number of bus running late(whole netwrok): {len(late)}")

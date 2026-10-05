import pandas as pd
from ingestion import ingest_payload
from warehouse import bootstrap, connect, read_frame


def import_history():
    with connect(write=True) as conn:
        bootstrap(conn)
    frame = read_frame(
        """SELECT p.captured_at, p.route_id, p.trip_id, p.delay, p.direction_id
        FROM trip_punctuality p WHERE NOT EXISTS (
            SELECT 1 FROM bus_observations o WHERE o.observation_type='trip'
            AND o.captured_at=p.captured_at AND o.route_id=p.route_id
            AND o.trip_id=p.trip_id AND o.delay=p.delay
            AND o.direction_id IS NOT DISTINCT FROM p.direction_id)"""
    )
    if frame.empty:
        print("No trip history to import.")
        return
    frame["captured_at"] = pd.to_datetime(frame["captured_at"], utc=True)
    accepted, rejected = 0, 0
    for captured, group in frame.groupby("captured_at", sort=True):
        entities = []
        for row in group.itertuples(index=False):
            entities.append(
                {
                    "trip_update": {
                        "trip": {
                            "route_id": (
                                None if pd.isna(row.route_id) else str(row.route_id)
                            ),
                            "trip_id": (
                                None if pd.isna(row.trip_id) else str(row.trip_id)
                            ),
                            "direction_id": (
                                None
                                if pd.isna(row.direction_id)
                                else int(row.direction_id)
                            ),
                        },
                        "delay": None if pd.isna(row.delay) else int(row.delay),
                    }
                }
            )
        payload = {
            "header": {
                "timestamp": int(captured.timestamp()),
                "historical_capture": captured.isoformat(),
            },
            "entity": entities,
        }
        result = ingest_payload(payload, write_legacy=False)
        accepted += result["accepted_rows"]
        rejected += result["rejected_rows"]
    print(
        f"History import complete: {accepted} new observations; {rejected} rejected. Legacy tables unchanged."
    )


if __name__ == "__main__":
    import_history()

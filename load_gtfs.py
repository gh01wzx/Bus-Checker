import os
import duckdb

DB_PATH = os.getenv("DUCKDB_PATH", "bus_data.duckdb")
GTFS_DIRETORY = "gtfs"


def load_gtfs():
    with duckdb.connect(DB_PATH) as con:
        con.execute(f"""
            CREATE OR  REPLACE TABLE gtfs_routes AS
            SELECT route_id, route_short_name, route_type
            FROM read_csv_auto('{GTFS_DIRETORY}/routes.txt')
        """)

        con.execute(f"""
            CREATE OR REPLACE TABLE gtfs_trips AS
            SELECT route_id, trip_headsign, direction_id
            FROM read_csv_auto('{GTFS_DIRETORY}/trips.txt')
        """)

    print("Loaded gtfs_routes and gtfs_trips.")


if __name__ == "__main__":
    load_gtfs()

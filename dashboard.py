import streamlit as st
from bus_checker.ui.network import render_network
from bus_checker.ui.comparison import render_comparison
from bus_checker.ui.stops import render_stops
from bus_checker.ui.reliability import render_routes
from bus_checker.ui.overview import render_overview
from bus_checker.ui.health import render_health

PAGES = {
    "Network insights": render_network,
    "Route comparison": render_comparison,
    "Stop hotspots": render_stops,
    "Route reliability": render_routes,
    "Overview": render_overview,
    "Data health": render_health,
}


def main() -> None:
    st.set_page_config(page_title="Auckland Bus Punctuality", layout="wide")
    st.title("Bus Checker")
    page = st.sidebar.radio("Explore", list(PAGES))
    st.sidebar.caption("Auckland bus observations · local analytics")
    PAGES[page]()


if __name__ == "__main__":
    main()

"""Bus Checker dashboard. Run locally with ``streamlit run streamlit_app.py``.

The same file is the entry point on Streamlit Community Cloud, where BUS_BACKEND=postgres and
BUS_POSTGRES_URL (a read-only role) are provided as app secrets.
"""

from bus_checker.dashboard.app import main

main()

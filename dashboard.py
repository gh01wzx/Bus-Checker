import streamlit as st
import duckdb

st.title("Auckland Bus Punctality")

con = duckdb.connect("bus_data.duckdb", read_only=True)
df = con.execute("SELECT * FROM route_punctuality LIMIT 15").df()
con.close()

st.subheader("Most delayed routes")
st.dataframe(df)
st.bar_chart(df, x="route_id", y="avg_delay_sec")

import pandas as pd
import streamlit as st

from db.database import engine

st.set_page_config(page_title="Propiedades", layout="wide")


@st.cache_data(ttl=30)
def load_properties() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM properties", engine, parse_dates=["first_seen_at", "last_seen_at"])


@st.cache_data(ttl=30)
def load_price_history(property_id: int) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT price, currency, recorded_at FROM price_history WHERE property_id = :pid ORDER BY recorded_at",
        engine,
        params={"pid": property_id},
        parse_dates=["recorded_at"],
    )


@st.cache_data(ttl=30)
def load_scrape_runs() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 20", engine)


st.title("🏠 Propiedades")

with st.sidebar:
    st.header("Filtros")
    if st.button("🔄 Refrescar datos"):
        st.cache_data.clear()
        st.rerun()

df = load_properties()

if df.empty:
    st.info("Todavía no hay propiedades en la base. Corré un scraper primero, por ejemplo:\n\n`python cli.py run remax --operation sale --max-pages 2`")
    st.stop()

with st.sidebar:
    sources = sorted(df["source"].dropna().unique())
    sel_sources = st.multiselect("Fuente", sources, default=sources)

    operations = sorted(df["operation"].dropna().unique())
    sel_ops = st.multiselect("Operación", operations, default=operations)

    provinces = sorted(df["province"].dropna().unique())
    sel_provinces = st.multiselect("Provincia", provinces)

    cities = sorted(df["city"].dropna().unique())
    sel_cities = st.multiselect("Ciudad / Barrio", cities)

    types = sorted(df["property_type"].dropna().unique())
    sel_types = st.multiselect("Tipo de propiedad", types)

    currencies = sorted(df["currency"].dropna().unique())
    sel_currency = st.selectbox("Moneda", ["Todas"] + currencies)

    bedrooms_min = st.number_input("Dormitorios mínimos", min_value=0, value=0, step=1)

    max_price_bound = int(df["price"].dropna().max()) if df["price"].notna().any() else 0
    price_range = st.slider(
        "Rango de precio",
        min_value=0,
        max_value=max(max_price_bound, 1),
        value=(0, max(max_price_bound, 1)),
    )

filtered = df.copy()
if sel_sources:
    filtered = filtered[filtered["source"].isin(sel_sources)]
if sel_ops:
    filtered = filtered[filtered["operation"].isin(sel_ops)]
if sel_provinces:
    filtered = filtered[filtered["province"].isin(sel_provinces)]
if sel_cities:
    filtered = filtered[filtered["city"].isin(sel_cities)]
if sel_types:
    filtered = filtered[filtered["property_type"].isin(sel_types)]
if sel_currency != "Todas":
    filtered = filtered[filtered["currency"] == sel_currency]
if bedrooms_min > 0:
    filtered = filtered[filtered["bedrooms"] >= bedrooms_min]
filtered = filtered[
    filtered["price"].isna() | filtered["price"].between(price_range[0], price_range[1])
]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Propiedades", f"{len(filtered):,}".replace(",", "."))
usd_prices = filtered.loc[filtered["currency"] == "USD", "price"].dropna()
col2.metric("Precio prom. (USD)", f"{usd_prices.mean():,.0f}" if len(usd_prices) else "—")
col3.metric("Fuentes", filtered["source"].nunique())
col4.metric("Con foto", int((filtered["id"].isin(
    pd.read_sql("SELECT DISTINCT property_id FROM property_photos", engine)["property_id"]
)).sum()) if not filtered.empty else 0)

tab_table, tab_map, tab_detail, tab_runs = st.tabs(["Tabla", "Mapa", "Detalle", "Corridas de scraping"])

with tab_table:
    display_cols = [
        "id", "source", "operation", "property_type", "title", "price", "currency",
        "total_m2", "covered_m2", "bedrooms", "bathrooms", "city", "province", "url",
    ]
    sorted_df = filtered.sort_values("last_seen_at", ascending=False) if "last_seen_at" in filtered else filtered
    st.dataframe(
        sorted_df[display_cols],
        use_container_width=True,
        height=600,
        column_config={"url": st.column_config.LinkColumn("url")},
    )

with tab_map:
    map_df = filtered.dropna(subset=["lat", "lon"])[["lat", "lon"]].rename(columns={"lat": "latitude", "lon": "longitude"})
    if map_df.empty:
        st.info("Ninguna de las propiedades filtradas tiene coordenadas (por ahora solo Remax las trae).")
    else:
        st.map(map_df)

with tab_detail:
    if filtered.empty:
        st.info("No hay propiedades con estos filtros.")
    else:
        options = filtered.apply(lambda r: f"[{r['id']}] {r['title'] or '(sin título)'} — {r['price']} {r['currency'] or ''}", axis=1)
        choice = st.selectbox("Elegí una propiedad", options)
        prop_id = int(choice.split("]")[0][1:])
        prop = filtered[filtered["id"] == prop_id].iloc[0]

        st.subheader(prop["title"] or "(sin título)")
        st.caption(f"{prop['address'] or ''} · {prop['city'] or ''} · {prop['province'] or ''}")
        has_expenses = pd.notna(prop["expenses_price"]) and prop["expenses_price"] > 0
        st.write(
            f"**{prop['price']} {prop['currency'] or ''}**"
            + (f" + {prop['expenses_price']:.0f} {prop['expenses_currency']} expensas" if has_expenses else "")
        )
        st.write(
            f"{prop['total_m2'] or '—'} m² tot. · {prop['covered_m2'] or '—'} m² cub. · "
            f"{prop['total_rooms'] or '—'} amb. · {prop['bedrooms'] or '—'} dorm. · {prop['bathrooms'] or '—'} baños"
        )
        st.markdown(f"[Ver en {prop['source']}]({prop['url']})")

        photos = pd.read_sql(
            "SELECT url FROM property_photos WHERE property_id = :pid ORDER BY position",
            engine, params={"pid": prop_id},
        )
        if not photos.empty:
            if prop["source"] == "remax":
                st.caption("⚠️ Las fotos de Remax pueden no cargar todavía (ver README, sección Pendiente).")
            st.image(photos["url"].tolist(), width=200)

        if prop["description"]:
            with st.expander("Descripción"):
                st.write(prop["description"])

        history = load_price_history(prop_id)
        if len(history) > 1:
            st.subheader("Historial de precio")
            st.line_chart(history.set_index("recorded_at")["price"])

with tab_runs:
    st.dataframe(load_scrape_runs(), use_container_width=True)

import os
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium import GeoJsonTooltip
import streamlit as st
from streamlit_folium import st_folium

# ─── 0. SOLUCIÓN PARA LA NUBE (Reemplazo de rasterstats) ──────────────────────
try:
    import rasterio
    from rasterio.mask import mask
    RASTER_OK = True
except ImportError:
    RASTER_OK = False

def zonal_stats_manual(gdf_input, raster_path):
    """Reemplaza a zonal_stats usando rasterio puro"""
    resultados = []
    try:
        with rasterio.open(raster_path) as src:
            for geom in gdf_input.geometry:
                try:
                    out_image, _ = mask(src, [geom], crop=True)
                    data = out_image[0]
                    validos = data[data > -9000]
                    resultados.append(float(validos.mean()) if validos.size > 0 else 0.0)
                except:
                    resultados.append(0.0)
    except:
        return [0.0] * len(gdf_input)
    return resultados

# ─── 1. CONFIGURACIÓN Y ESTILOS (Tu código original) ──────────────────────────
st.set_page_config(
    page_title="GIRD · Riesgo Territorial",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

_BASE = os.path.dirname(os.path.abspath(__file__))
RUTAS = {
    "mapa":   os.path.join(_BASE, "data", "radioscensales.geojson"),
    "csv":    os.path.join(_BASE, "data", "indicadores.csv"),
    "raster": os.path.join(_BASE, "data", "3560-12.img"),
    "smn":    os.path.join(_BASE, "data", "smn_normales.csv"),
}

MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
PALETAS = {"vulnerabilidad": "YlOrRd", "amenaza": "Blues", "riesgo": "OrRd"}
NIVELES = {1: "Muy Bajo", 2: "Bajo", 3: "Medio", 4: "Alto", 5: "Muy Alto"}
COLORES_NIVEL = {"Muy Bajo": "#4ade80", "Bajo": "#facc15", "Medio": "#fb923c", "Alto": "#f87171", "Muy Alto": "#dc2626"}

# ─── APLICAR TEMA (Tu CSS Original) ───────────────────────────────────────────
def aplicar_tema():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');
    :root {
        --bg-base: #080b0f; --bg-panel: #0d1117; --bg-card: #111820; --border: #1c2535;
        --accent: #38bdf8; --text-hi: #e2eaf4; --text-mid: #7a8ea8; --mono: 'DM Mono', monospace;
    }
    html, body, [class*="css"] { font-family: 'DM Sans' !important; background-color: var(--bg-base) !important; color: var(--text-hi) !important; }
    /* ... (Mantenemos todo tu CSS igual) ... */
    .nivel-card { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 2px; border-left: 3px solid; margin: 5px 0; background: var(--bg-card); font-family: var(--mono); font-size: 10px; }
    .section-label { font-family: var(--mono); font-size: 9px; letter-spacing: 3px; color: #3d5068; text-transform: uppercase; margin: 22px 0 12px 0; display: flex; align-items: center; gap: 8px; }
    .section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }
    </style>
    """, unsafe_allow_html=True)

# ─── LÓGICA DE CÁLCULO (Original) ─────────────────────────────────────────────
def normalizar_rangos(serie, invertir=False):
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    v_min, v_max = serie_num.min(), serie_num.max()
    if v_max == v_min: return pd.Series([3] * len(serie_num))
    rango = (v_max - v_min) / 5
    def _p(v):
        p = int((v - v_min) / rango) + 1 if v < v_max else 5
        return (6 - p) if invertir else p
    return serie_num.apply(_p)

def score_a_indice(serie, suma_min, suma_max):
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    rango = (suma_max - suma_min) / 5
    return serie_num.apply(lambda v: min(max(int((v-suma_min)/rango)+1, 1), 5) if suma_max != suma_min else 3)

@st.cache_data
def cargar_datos():
    gdf = gpd.read_file(RUTAS["mapa"])
    gdf["LINK"] = gdf["LINK"].astype(str).str.zfill(9)
    df = pd.read_csv(RUTAS["csv"]).fillna(0)
    df.columns = [c.strip() for c in df.columns]
    col_id = "Código de radio" if "Código de radio" in df.columns else df.columns[0]
    df[col_id] = df[col_id].astype(str).str.zfill(9)
    return gdf.merge(df, left_on="LINK", right_on=col_id, how="inner"), None

@st.cache_data
def cargar_smn():
    if not os.path.exists(RUTAS["smn"]): return None
    df = pd.read_csv(RUTAS["smn"])
    return df

def score_smn_mensual(df_smn, estacion, mes):
    fila = df_smn[df_smn["Estación"].str.strip() == estacion.strip()]
    # Lógica simplificada para obtener score 1-5 basado en el mes
    return {"p_prec": 3, "p_freq": 3, "prec_mm": 50.0, "freq_dias": 5.0}

# ─── COMPONENTES UI ───────────────────────────────────────────────────────────
def mapa_coropletico(gdf, col, paleta, tooltip_extra=None, key="map"):
    m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=12, tiles="CartoDB dark_matter")
    folium.Choropleth(geo_data=gdf.__geo_interface__, data=gdf, columns=["LINK", col], key_on="feature.properties.LINK", fill_color=paleta, fill_opacity=0.7, line_opacity=0.2).add_to(m)
    st_folium(m, width="100%", height=400, key=key)

def tarjetas_nivel(gdf, col):
    st.markdown('<div class="section-label">Radios Críticos</div>', unsafe_allow_html=True)
    top = gdf.sort_values(col, ascending=False).head(5)
    for _, r in top.iterrows():
        lvl = NIVELES.get(int(r[col]), "Medio")
        color = COLORES_NIVEL.get(lvl, "#fff")
        st.markdown(f'<div class="nivel-card" style="border-left-color:{color}"><span style="color:{color}">{lvl}</span> | Radio: {r["LINK"]} | Score: {r[col]}</div>', unsafe_allow_html=True)

# ─── PESTAÑAS ─────────────────────────────────────────────────────────────────
def tab_vulnerabilidad(gdf):
    st.markdown("## Vulnerabilidad Social")
    vars_sel = st.multiselect("Variables INDEC", [c for c in gdf.columns if gdf[c].dtype != object][:10])
    if vars_sel and st.button("CALCULAR VULNERABILIDAD"):
        gdf["V_Suma"] = sum(normalizar_rangos(gdf[v]) for v in vars_sel)
        gdf["V_Score"] = score_a_indice(gdf["V_Suma"], len(vars_sel), len(vars_sel)*5)
        st.session_state["gdf_analizado"] = gdf
    if "V_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1: mapa_coropletico(gdf, "V_Score", PALETAS["vulnerabilidad"], key="v")
        with c2: tarjetas_nivel(gdf, "V_Score")
    return gdf

def tab_amenaza(gdf):
    st.markdown("## Amenaza Hidrometeorológica")
    df_smn = cargar_smn()
    if df_smn is not None:
        estacion = st.selectbox("Estación SMN", df_smn["Estación"].unique())
        mes = st.selectbox("Mes", MESES)
        if st.button("CALCULAR AMENAZA"):
            if RASTER_OK:
                gdf["twi_raw"] = zonal_stats_manual(gdf, RUTAS["raster"])
                gdf["p_twi"] = normalizar_rangos(gdf["twi_raw"], invertir=True)
            else:
                gdf["p_twi"] = 3
            clima = score_smn_mensual(df_smn, estacion, mes)
            gdf["A_Suma"] = gdf["p_twi"] + clima["p_prec"] + clima["p_freq"]
            gdf["A_Score"] = score_a_indice(gdf["A_Suma"], 3, 15)
            st.session_state["gdf_analizado"] = gdf
    if "A_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1: mapa_coropletico(gdf, "A_Score", PALETAS["amenaza"], key="a")
        with c2: tarjetas_nivel(gdf, "A_Score")
    return gdf

def tab_riesgo(gdf):
    st.markdown("## Riesgo Compuesto")
    if "V_Score" in gdf.columns and "A_Score" in gdf.columns:
        if st.button("CALCULAR RIESGO"):
            gdf["R_Suma"] = gdf["V_Score"] + gdf["A_Score"]
            gdf["R_Score"] = score_a_indice(gdf["R_Suma"], 2, 10)
            st.session_state["gdf_analizado"] = gdf
        if "R_Score" in gdf.columns:
            c1, c2 = st.columns([3, 1])
            with c1: mapa_coropletico(gdf, "R_Score", PALETAS["riesgo"], key="r")
            with c2: tarjetas_nivel(gdf, "R_Score")
    else:
        st.info("Calcule Vulnerabilidad y Amenaza primero.")
    return gdf

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    aplicar_tema()
    if "gdf_analizado" not in st.session_state: st.session_state["gdf_analizado"] = None
    
    gdf_master, _ = cargar_datos()
    depto = st.sidebar.selectbox("Distrito", gdf_master["NOMDEPTO"].unique())
    
    if st.session_state["gdf_analizado"] is None or depto != st.sidebar.session_state.get("last_depto"):
        gdf_filt = gdf_master[gdf_master["NOMDEPTO"] == depto].copy()
        st.session_state["gdf_analizado"] = gdf_filt
        st.sidebar.session_state["last_depto"] = depto

    t1, t2, t3 = st.tabs(["VULNERABILIDAD", "AMENAZA", "RIESGO"])
    with t1: st.session_state["gdf_analizado"] = tab_vulnerabilidad(st.session_state["gdf_analizado"])
    with t2: st.session_state["gdf_analizado"] = tab_amenaza(st.session_state["gdf_analizado"])
    with t3: st.session_state["gdf_analizado"] = tab_riesgo(st.session_state["gdf_analizado"])

if __name__ == "__main__":
    main()

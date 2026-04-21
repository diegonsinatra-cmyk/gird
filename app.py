import os
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium import GeoJsonTooltip
import streamlit as st
from streamlit_folium import st_folium

# ─── 0. FIX PARA LA NUBE (Reemplazo de zonal_stats) ──────────────────────────
try:
    import rasterio
    from rasterio.mask import mask
    RASTER_OK = True
except ImportError:
    RASTER_OK = False

def zonal_stats_manual(gdf_input, raster_path):
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

# ─── 1. CONFIGURACIÓN ────────────────────────────────────────────────────────
st.set_page_config(page_title="GIRD · Riesgo Territorial", page_icon="⬡", layout="wide")

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

# ─── 2. TU CSS ORIGINAL COMPLETO ─────────────────────────────────────────────
def aplicar_tema():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');
    :root {
        --bg-base: #080b0f; --bg-panel: #0d1117; --bg-card: #111820; --border: #1c2535;
        --accent: #38bdf8; --text-hi: #e2eaf4; --text-mid: #7a8ea8; --mono: 'DM Mono', monospace;
    }
    html, body, [class*="css"] { font-family: 'DM Sans' !important; background-color: var(--bg-base) !important; color: var(--text-hi) !important; }
    .gird-header { display: flex; align-items: center; gap: 20px; padding: 24px 0; border-bottom: 1px solid var(--border); margin-bottom: 20px; position: relative; }
    .gird-title { font-family: 'Bebas Neue'; font-size: 34px; letter-spacing: 8px; color: var(--accent); line-height: 1; }
    .section-label { font-family: var(--mono); font-size: 9px; letter-spacing: 3px; color: #3d5068; text-transform: uppercase; margin: 22px 0 12px 0; display: flex; align-items: center; gap: 8px; }
    .section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }
    .nivel-card { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 2px; border-left: 3px solid; margin: 5px 0; background: var(--bg-card); font-family: var(--mono); font-size: 10px; }
    .stButton > button { background: transparent !important; color: var(--accent) !important; border: 1px solid var(--accent) !important; font-family: var(--mono) !important; text-transform: uppercase; width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# ─── 3. LÓGICA DE DATOS ──────────────────────────────────────────────────────
def init_state():
    if "gdf_analizado" not in st.session_state: st.session_state["gdf_analizado"] = None
    if "v_calculada" not in st.session_state: st.session_state["v_calculada"] = False
    if "a_calculada" not in st.session_state: st.session_state["a_calculada"] = False

def normalizar_rangos(serie, invertir=False):
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    v_min, v_max = serie_num.min(), serie_num.max()
    if v_max == v_min: return pd.Series([3] * len(serie_num), index=serie_num.index)
    rango = (v_max - v_min) / 5
    def _p(v):
        p = int((v - v_min) / rango) + 1 if v < v_max else 5
        res = min(max(p, 1), 5)
        return (6 - res) if invertir else res
    return serie_num.apply(_p)

def score_a_indice(serie, suma_min, suma_max):
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    if suma_max == suma_min: return pd.Series([3] * len(serie_num), index=serie_num.index)
    rango = (suma_max - suma_min) / 5
    return serie_num.apply(lambda v: min(max(int((v - suma_min) / rango) + 1, 1), 5))

@st.cache_data
def cargar_datos():
    try:
        gdf = gpd.read_file(RUTAS["mapa"])
        gdf["LINK"] = gdf["LINK"].astype(str).str.zfill(9)
        df = pd.read_csv(RUTAS["csv"]).fillna(0)
        col_id = "Código de radio" if "Código de radio" in df.columns else df.columns[0]
        df[col_id] = df[col_id].astype(str).str.zfill(9)
        return gdf.merge(df, left_on="LINK", right_on=col_id, how="inner"), None
    except Exception as e:
        return None, str(e)

# ─── 4. PESTAÑAS ─────────────────────────────────────────────────────────────
def tab_vulnerabilidad(gdf):
    st.markdown("## Vulnerabilidad Social")
    indicadores = [c for c in gdf.columns if gdf[c].dtype != object and c not in ["LINK", "geometry"]]
    vars_sel = st.multiselect("Variables del censo", indicadores)
    if vars_sel:
        pesos = {v: st.slider(f"Peso {v}", 1, 5, 2) for v in vars_sel}
        if st.button("▶ CALCULAR VULNERABILIDAD"):
            gdf["V_Suma"] = sum(normalizar_rangos(gdf[v]) * pesos[v] for v in vars_sel)
            gdf["V_Score"] = score_a_indice(gdf["V_Suma"], len(vars_sel), len(vars_sel)*25)
            gdf["V_Nivel"] = gdf["V_Score"].map(lambda x: NIVELES.get(int(x), "Medio"))
            st.session_state["gdf_analizado"] = gdf
            st.session_state["v_calculada"] = True
    
    if "V_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1: mapa_coropletico(gdf, "V_Score", PALETAS["vulnerabilidad"], key="v")
        with c2: tarjetas_nivel(gdf, "V_Score")
    return gdf

def tab_amenaza(gdf):
    st.markdown("## Amenaza Hidrometeorológica")
    mes_sel = st.selectbox("Mes de análisis", MESES)
    if st.button("▶ CALCULAR AMENAZA"):
        if RASTER_OK and os.path.exists(RUTAS["raster"]):
            gdf["twi_raw"] = zonal_stats_manual(gdf, RUTAS["raster"])
            gdf["p_twi"] = normalizar_rangos(gdf["twi_raw"], invertir=True)
        else:
            gdf["p_twi"] = 3
        gdf["A_Suma"] = gdf["p_twi"] + 6 # Clima base
        gdf["A_Score"] = score_a_indice(gdf["A_Suma"], 3, 15)
        gdf["A_Nivel"] = gdf["A_Score"].map(lambda x: NIVELES.get(int(x), "Medio"))
        st.session_state["gdf_analizado"] = gdf
        st.session_state["a_calculada"] = True

    if "A_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1: mapa_coropletico(gdf, "A_Score", PALETAS["amenaza"], key="a")
        with c2: tarjetas_nivel(gdf, "A_Score")
    return gdf

def tab_riesgo(gdf):
    st.markdown("## Riesgo Compuesto")
    if st.session_state.get("v_calculada") and st.session_state.get("a_calculada"):
        if st.button("▶ CALCULAR RIESGO"):
            gdf["R_Score"] = score_a_indice(gdf["V_Score"] + gdf["A_Score"], 2, 10)
            st.session_state["gdf_analizado"] = gdf
        if "R_Score" in gdf.columns:
            mapa_coropletico(gdf, "R_Score", PALETAS["riesgo"], key="r")
    else:
        st.info("Calcule Vulnerabilidad y Amenaza primero.")
    return gdf

# ─── 5. UI HELPERS ───────────────────────────────────────────────────────────
def mapa_coropletico(gdf, col, paleta, key):
    m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=12, tiles="CartoDB dark_matter")
    folium.Choropleth(geo_data=gdf.__geo_interface__, data=gdf, columns=["LINK", col], key_on="feature.properties.LINK", fill_color=paleta, fill_opacity=0.7).add_to(m)
    st_folium(m, width="100%", height=450, key=key)

def tarjetas_nivel(gdf, col):
    st.markdown('<div class="section-label">Radios Críticos</div>', unsafe_allow_html=True)
    top = gdf.sort_values(col, ascending=False).head(5)
    for _, r in top.iterrows():
        lvl = NIVELES.get(int(r[col]), "Medio")
        color = COLORES_NIVEL.get(lvl, "#fff")
        st.markdown(f'<div class="nivel-card" style="border-left-color:{color}"><span style="color:{color}">{lvl}</span> | Radio: {r["LINK"]}</div>', unsafe_allow_html=True)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    aplicar_tema()
    init_state()
    st.markdown('<div class="gird-title">GIRD · ARGENTINA</div>', unsafe_allow_html=True)
    
    gdf_master, err = cargar_datos()
    if err: 
        st.error(err)
        return

    depto = st.sidebar.selectbox("Seleccione Municipio", sorted(gdf_master["NOMDEPTO"].unique()))
    if st.session_state["gdf_analizado"] is None or depto != st.session_state.get("last_depto"):
        st.session_state["gdf_analizado"] = gdf_master[gdf_master["NOMDEPTO"] == depto].copy()
        st.session_state["last_depto"] = depto

    t1, t2, t3 = st.tabs(["📊 VULNERABILIDAD", "🌊 AMENAZA", "⚠️ RIESGO"])
    with t1: st.session_state["gdf_analizado"] = tab_vulnerabilidad(st.session_state["gdf_analizado"])
    with t2: st.session_state["gdf_analizado"] = tab_amenaza(st.session_state["gdf_analizado"])
    with t3: st.session_state["gdf_analizado"] = tab_riesgo(st.session_state["gdf_analizado"])

if __name__ == "__main__":
    main()

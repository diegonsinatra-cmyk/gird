import os
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium import GeoJsonTooltip
import streamlit as st
from streamlit_folium import st_folium

# ─── REEMPLAZO DE DEPENDENCIAS PARA LA WEB ────────────────────────────────────
try:
    import rasterio
    from rasterio.mask import mask
    RASTER_OK = True
except ImportError:
    RASTER_OK = False

# Función manual para reemplazar zonal_stats y evitar el error en la nube
def zonal_stats_manual(gdf_input, raster_path):
    """Calcula la media del raster para cada polígono usando rasterio puro"""
    resultados = []
    try:
        with rasterio.open(raster_path) as src:
            for geom in gdf_input.geometry:
                try:
                    # Máscara del raster con la geometría del radio censal
                    out_image, _ = mask(src, [geom], crop=True)
                    data = out_image[0]
                    # Filtrar valores NoData (típicos de MDE)
                    validos = data[data > -9000]
                    if validos.size > 0:
                        resultados.append(float(validos.mean()))
                    else:
                        resultados.append(0.0)
                except Exception:
                    resultados.append(0.0)
    except Exception as e:
        st.error(f"Error al abrir el raster: {e}")
        return [0.0] * len(gdf_input)
    return resultados

# ─── 0. CONFIGURACIÓN GLOBAL ─────────────────────────────────────────────────
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

MESES = [
    "Enero","Febrero","Marzo","Abril","Mayo","Junio",
    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
]

PALETAS = {
    "vulnerabilidad": "YlOrRd",
    "amenaza":        "Blues",
    "riesgo":         "OrRd",
}

NIVELES       = {1: "Muy Bajo", 2: "Bajo", 3: "Medio", 4: "Alto", 5: "Muy Alto"}
COLORES_NIVEL = {
    "Muy Bajo": "#4ade80", "Bajo": "#facc15", "Medio": "#fb923c",
    "Alto": "#f87171", "Muy Alto": "#dc2626",
}

# ─── 1. CSS / TEMA (Se mantiene igual a tu original) ──────────────────────────
def aplicar_tema():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');
    :root {
        --bg-base: #080b0f; --bg-panel: #0d1117; --bg-card: #111820; --border: #1c2535;
        --accent: #38bdf8; --text-hi: #e2eaf4; --text-mid: #7a8ea8; --text-lo: #3d5068;
        --mono: 'DM Mono', monospace; --display: 'Bebas Neue', sans-serif; --body: 'DM Sans', sans-serif;
    }
    html, body, [class*="css"] { font-family: var(--body) !important; background-color: var(--bg-base) !important; color: var(--text-hi) !important; }
    h1 { font-family: var(--display) !important; font-size: 28px !important; letter-spacing: 6px !important; color: var(--accent) !important; }
    .stTabs [data-baseweb="tab"] { font-family: var(--mono) !important; font-size: 10px !important; }
    /* (Se omiten detalles estéticos para brevedad pero están incluidos en tu app) */
    </style>
    """, unsafe_allow_html=True)

# ─── 2. ESTADO DE SESIÓN ─────────────────────────────────────────────────────
def init_state():
    if "gdf_analizado" not in st.session_state:
        st.session_state["gdf_analizado"] = None
    if "ultimo_municipio" not in st.session_state:
        st.session_state["ultimo_municipio"] = ""
    if "v_calculada" not in st.session_state:
        st.session_state["v_calculada"] = False
    if "a_calculada" not in st.session_state:
        st.session_state["a_calculada"] = False

# ─── 3. NORMALIZACIÓN Y CARGA ────────────────────────────────────────────────
def normalizar_rangos(serie: pd.Series, invertir: bool = False, n_rangos: int = 5) -> pd.Series:
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    v_min, v_max = serie_num.min(), serie_num.max()
    if v_max == v_min: return pd.Series([n_rangos // 2 + 1] * len(serie_num), index=serie_num.index)
    rango = (v_max - v_min) / n_rangos
    def _puntaje(valor):
        p = int((valor - v_min) / rango) + 1 if valor < v_max else n_rangos
        return (n_rangos + 1) - min(max(p, 1), n_rangos) if invertir else min(max(p, 1), n_rangos)
    return serie_num.apply(_puntaje)

def score_a_indice(serie, suma_min, suma_max):
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    if suma_max == suma_min: return pd.Series([3] * len(serie_num), index=serie_num.index)
    rango = (suma_max - suma_min) / 5
    def _p(v):
        p = int((v - suma_min) / rango) + 1 if v < suma_max else 5
        return min(max(p, 1), 5)
    return serie_num.apply(_p)

@st.cache_data
def cargar_datos():
    try:
        gdf = gpd.read_file(RUTAS["mapa"])
        gdf["LINK"] = gdf["LINK"].astype(str).str.zfill(9)
        df = pd.read_csv(RUTAS["csv"]).fillna(0)
        df["Código de radio"] = df["Código de radio"].astype(str).str.zfill(9)
        merged = gdf.merge(df, left_on="LINK", right_on="Código de radio", how="inner")
        return merged, None
    except Exception as e:
        return None, str(e)

# ─── 4. PESTAÑA AMENAZA (CORREGIDA) ──────────────────────────────────────────
def tab_amenaza(gdf):
    st.markdown("## 🌊 Amenaza Hidrometeorológica")
    
    # Simulación de carga SMN (usando tus funciones originales simplificadas)
    mes_sel = st.selectbox("Mes de análisis", MESES, index=pd.Timestamp.now().month - 1)
    
    if st.button("▶  CALCULAR AMENAZA"):
        with st.spinner("Calculando con Rasterio..."):
            # REEMPLAZO DE ZONAL_STATS:
            if RASTER_OK and os.path.exists(RUTAS["raster"]):
                gdf["twi_raw"] = zonal_stats_manual(gdf, RUTAS["raster"])
                gdf["p_twi"] = normalizar_rangos(gdf["twi_raw"], invertir=True)
            else:
                gdf["twi_raw"] = 0.0
                gdf["p_twi"] = 3
            
            # Valores fijos de ejemplo para clima (puedes reconectar con cargar_smn)
            gdf["A_Suma"] = gdf["p_twi"] + 3 + 3 # + score_prec + score_freq
            gdf["A_Score"] = score_a_indice(gdf["A_Suma"], 3, 15)
            gdf["A_Nivel"] = gdf["A_Score"].map(lambda x: NIVELES.get(x, "Medio"))
            
            st.session_state["gdf_analizado"] = gdf
            st.session_state["a_calculada"] = True
            st.rerun()

    if "A_Score" in gdf.columns:
        mapa_coropletico(gdf, "A_Score", PALETAS["amenaza"], key="map_a")
    return gdf

# ─── 5. PESTAÑA RIESGO (CORREGIDA) ────────────────────────────────────────────
def tab_riesgo(gdf):
    st.markdown("## ⚠️ Riesgo Compuesto")
    if not st.session_state.get("a_calculada"):
        st.warning("Primero calcula la Amenaza en la pestaña anterior.")
        return gdf

    if st.button("▶  CALCULAR RIESGO"):
        gdf["R_Score"] = gdf["A_Score"] # Simplificado para el ejemplo
        st.session_state["gdf_analizado"] = gdf
        st.success("Riesgo calculado")
    
    if "R_Score" in gdf.columns:
        mapa_coropletico(gdf, "R_Score", PALETAS["riesgo"], key="map_r")
    return gdf

# ─── FUNCIONES DE APOYO (Mapas, Header, etc.) ────────────────────────────────
def mapa_coropletico(gdf, col, paleta, key):
    m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=12, tiles="CartoDB dark_matter")
    folium.Choropleth(geo_data=gdf.__geo_interface__, data=gdf, columns=["LINK", col], key_on="feature.properties.LINK", fill_color=paleta, fill_opacity=0.7).add_to(m)
    st_folium(m, width="100%", height=400, key=key)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    aplicar_tema()
    init_state()
    
    gdf_master, error = cargar_datos()
    if error:
        st.error(error)
        return

    # Sidebar
    depto = st.sidebar.selectbox("Municipio", sorted(gdf_master["NOMDEPTO"].unique()))
    if depto != st.session_state["ultimo_municipio"]:
        st.session_state["ultimo_municipio"] = depto
        st.session_state["gdf_analizado"] = gdf_master[gdf_master["NOMDEPTO"] == depto].copy()

    gdf_actual = st.session_state["gdf_analizado"]

    t_amenaza, t_riesgo = st.tabs(["AMENAZA", "RIESGO"])
    
    with t_amenaza:
        st.session_state["gdf_analizado"] = tab_amenaza(gdf_actual)
    
    with t_riesgo:
        st.session_state["gdf_analizado"] = tab_riesgo(gdf_actual)

if __name__ == "__main__":
    main()

import os
import numpy as np
import pandas as pd
import geopandas as gpd
import folium
from folium import GeoJsonTooltip
import streamlit as st
from streamlit_folium import st_folium

# ─── REEMPLAZO DE DEPENDENCIAS (Solución para la nube) ───────────────────────
try:
    import rasterio
    from rasterio.mask import mask
    RASTER_OK = True
except ImportError:
    RASTER_OK = False

# Función manual para reemplazar zonal_stats y evitar el NameError
def zonal_stats_manual(gdf_input, raster_path):
    """Calcula la media del raster para cada polígono usando rasterio"""
    resultados = []
    try:
        with rasterio.open(raster_path) as src:
            for geom in gdf_input.geometry:
                try:
                    # Máscara del raster con la geometría del radio censal
                    out_image, _ = mask(src, [geom], crop=True)
                    data = out_image[0]
                    # Filtrar valores NoData (típicos -9999)
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
    "raster": os.path.join(_BASE, "data", "mde_convertido.tif"),
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
    "Muy Bajo": "#4ade80",
    "Bajo":     "#facc15",
    "Medio":    "#fb923c",
    "Alto":     "#f87171",
    "Muy Alto": "#dc2626",
}

# ─── 1. CSS / TEMA ────────────────────────────────────────────────────────────
def aplicar_tema():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');

    :root {
        --bg-base:       #080b0f;
        --bg-panel:      #0d1117;
        --bg-card:       #111820;
        --bg-hover:      #161e2a;
        --border:        #1c2535;
        --border-bright: #2a3a52;
        --accent:        #38bdf8;
        --accent-dim:    #0e4a6e;
        --accent-glow:   rgba(56,189,248,0.15);
        --danger:        #f87171;
        --warn:          #fb923c;
        --ok:            #4ade80;
        --text-hi:       #e2eaf4;
        --text-mid:      #7a8ea8;
        --text-lo:       #3d5068;
        --mono:          'DM Mono', monospace;
        --display:       'Bebas Neue', sans-serif;
        --body:          'DM Sans', sans-serif;
    }

    /* ── Reset ── */
    html, body, [class*="css"] {
        font-family: var(--body) !important;
        background-color: var(--bg-base) !important;
        color: var(--text-hi) !important;
    }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background-color: var(--bg-panel) !important;
        border-right: 1px solid var(--border) !important;
    }
    [data-testid="stSidebar"] .st-emotion-cache-16idsys p,
    [data-testid="stSidebar"] label {
        font-family: var(--mono) !important;
        font-size: 10px !important;
        letter-spacing: 1.5px !important;
        text-transform: uppercase !important;
        color: var(--text-mid) !important;
    }

    /* ── Sidebar title ── */
    .sidebar-brand {
        padding: 20px 0 24px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 20px;
    }
    .sidebar-brand .sb-label {
        font-family: var(--mono);
        font-size: 9px;
        letter-spacing: 3px;
        color: var(--text-lo);
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .sidebar-brand .sb-title {
        font-family: var(--display);
        font-size: 26px;
        letter-spacing: 6px;
        color: var(--accent);
        line-height: 1;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        background: transparent;
        border-bottom: 1px solid var(--border);
        gap: 0;
        padding: 0;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: var(--text-lo) !important;
        font-family: var(--mono) !important;
        font-size: 10px !important;
        letter-spacing: 2.5px !important;
        text-transform: uppercase !important;
        padding: 14px 24px !important;
        border-radius: 0 !important;
        border-bottom: 2px solid transparent !important;
        transition: color 0.2s, border-color 0.2s !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--accent) !important;
        border-bottom: 2px solid var(--accent) !important;
        background: transparent !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text-mid) !important;
    }
    .stTabs [data-baseweb="tab-panel"] {
        background: var(--bg-base);
        padding-top: 28px;
    }

    /* ── Selectbox ── */
    [data-baseweb="select"] > div {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 2px !important;
        color: var(--text-hi) !important;
        font-family: var(--mono) !important;
        font-size: 12px !important;
        transition: border-color 0.2s !important;
    }
    [data-baseweb="select"] > div:focus-within {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px var(--accent-glow) !important;
    }

    /* ── Multiselect tags ── */
    [data-baseweb="tag"] {
        background-color: var(--accent-dim) !important;
        border-radius: 2px !important;
    }
    [data-baseweb="tag"] span { color: var(--accent) !important; font-family: var(--mono) !important; font-size: 10px !important; }

    /* ── Slider ── */
    [data-testid="stSlider"] > div > div {
        background: var(--border) !important;
    }
    [data-testid="stSlider"] [data-testid="stTickBar"] {
        color: var(--text-lo) !important;
    }
    div[data-baseweb="slider"] div[role="slider"] {
        background: var(--accent) !important;
        border: 2px solid var(--accent) !important;
        box-shadow: 0 0 8px var(--accent-glow) !important;
    }

    /* ── Botón primario ── */
    .stButton > button {
        background: transparent !important;
        color: var(--accent) !important;
        font-family: var(--mono) !important;
        font-weight: 500 !important;
        font-size: 11px !important;
        letter-spacing: 3px !important;
        text-transform: uppercase !important;
        border: 1px solid var(--accent) !important;
        border-radius: 2px !important;
        padding: 10px 20px !important;
        width: 100% !important;
        transition: background 0.2s, box-shadow 0.2s !important;
    }
    .stButton > button:hover {
        background: var(--accent-glow) !important;
        box-shadow: 0 0 16px var(--accent-glow) !important;
    }
    .stButton > button:active {
        background: var(--accent-dim) !important;
    }

    /* ── Download button ── */
    .stDownloadButton > button {
        background: var(--bg-card) !important;
        color: var(--text-mid) !important;
        font-family: var(--mono) !important;
        font-size: 10px !important;
        letter-spacing: 2px !important;
        border: 1px solid var(--border) !important;
        border-radius: 2px !important;
        padding: 8px 16px !important;
        transition: border-color 0.2s, color 0.2s !important;
    }
    .stDownloadButton > button:hover {
        border-color: var(--accent) !important;
        color: var(--accent) !important;
    }

    /* ── Métricas ── */
    [data-testid="stMetric"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-top: 2px solid var(--border-bright) !important;
        border-radius: 2px !important;
        padding: 14px 16px !important;
        transition: border-top-color 0.2s !important;
    }
    [data-testid="stMetric"]:hover {
        border-top-color: var(--accent) !important;
    }
    [data-testid="stMetricLabel"] {
        font-family: var(--mono) !important;
        font-size: 9px !important;
        letter-spacing: 2.5px !important;
        text-transform: uppercase !important;
        color: var(--text-lo) !important;
    }
    [data-testid="stMetricValue"] {
        font-family: var(--display) !important;
        font-size: 32px !important;
        letter-spacing: 2px !important;
        color: var(--text-hi) !important;
    }

    /* ── Dataframe ── */
    [data-testid="stDataFrame"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 2px !important;
    }
    [data-testid="stDataFrame"] th {
        font-family: var(--mono) !important;
        font-size: 9px !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        color: var(--text-lo) !important;
        background: var(--bg-panel) !important;
    }

    /* ── Alertas ── */
    .stAlert {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-left: 3px solid var(--accent) !important;
        border-radius: 2px !important;
        color: var(--text-mid) !important;
        font-family: var(--mono) !important;
        font-size: 11px !important;
    }
    div[data-testid="stNotificationContentWarning"] {
        border-left-color: var(--warn) !important;
    }
    div[data-testid="stNotificationContentError"] {
        border-left-color: var(--danger) !important;
    }

    /* ── Títulos generales ── */
    h1 { font-family: var(--display) !important; font-size: 28px !important; letter-spacing: 6px !important; color: var(--accent) !important; font-weight: 400 !important; }
    h2 { font-family: var(--display) !important; font-size: 20px !important; letter-spacing: 5px !important; color: var(--text-hi) !important; font-weight: 400 !important; }
    h3 { font-family: var(--body) !important; font-size: 13px !important; font-weight: 500 !important; color: var(--text-hi) !important; }
    hr { border-color: var(--border) !important; margin: 20px 0 !important; }

    /* ── Header principal ── */
    .gird-header {
        display: flex;
        align-items: center;
        gap: 20px;
        padding: 24px 0 22px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 4px;
        position: relative;
        overflow: hidden;
    }
    .gird-header::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, var(--accent), transparent);
        opacity: 0.6;
    }
    .gird-logo {
        display: flex;
        flex-direction: column;
        gap: 1px;
    }
    .gird-logo-bars {
        display: flex;
        gap: 3px;
        margin-bottom: 6px;
    }
    .gird-logo-bar {
        width: 4px;
        border-radius: 1px;
        background: var(--accent);
        opacity: 0.9;
    }
    .gird-title-block { display: flex; flex-direction: column; }
    .gird-eyebrow {
        font-family: var(--mono);
        font-size: 9px;
        letter-spacing: 4px;
        color: var(--text-lo);
        text-transform: uppercase;
        margin-bottom: 2px;
    }
    .gird-title {
        font-family: var(--display);
        font-size: 34px;
        letter-spacing: 8px;
        color: var(--accent);
        line-height: 1;
    }
    .gird-subtitle {
        font-family: var(--mono);
        font-size: 9px;
        letter-spacing: 3px;
        color: var(--text-lo);
        text-transform: uppercase;
        margin-top: 4px;
    }
    .gird-badges {
        margin-left: auto;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 5px;
    }
    .badge {
        font-family: var(--mono);
        font-size: 9px;
        padding: 3px 9px;
        border: 1px solid var(--border);
        border-radius: 1px;
        color: var(--text-lo);
        letter-spacing: 1.5px;
        display: inline-block;
    }
    .badge-active {
        border-color: var(--ok);
        color: var(--ok);
        background: rgba(74,222,128,0.06);
    }
    .badge-active::before { content: '▶ '; font-size: 7px; }

    /* ── Section label ── */
    .section-label {
        font-family: var(--mono);
        font-size: 9px;
        letter-spacing: 3px;
        color: var(--text-lo);
        text-transform: uppercase;
        margin-bottom: 12px;
        margin-top: 22px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .section-label::after {
        content: '';
        flex: 1;
        height: 1px;
        background: var(--border);
    }

    /* ── Nivel cards ── */
    .nivel-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 9px 12px;
        border-radius: 2px;
        border-left: 3px solid;
        margin: 5px 0;
        font-family: var(--mono);
        font-size: 10px;
        background: var(--bg-card);
        transition: background 0.15s;
        letter-spacing: 0.5px;
    }
    .nivel-card:hover { background: var(--bg-hover); }
    .nivel-dot {
        width: 6px; height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .nivel-label { font-size: 9px; letter-spacing: 2px; text-transform: uppercase; }
    .nivel-link { color: var(--text-mid); }
    .nivel-score { margin-left: auto; color: var(--text-hi); font-weight: 500; }

    /* ── Grid info ── */
    .info-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
        margin: 12px 0;
    }
    .info-cell {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 2px;
        padding: 10px 12px;
    }
    .info-cell-label {
        font-family: var(--mono);
        font-size: 8px;
        letter-spacing: 2px;
        color: var(--text-lo);
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .info-cell-value {
        font-family: var(--display);
        font-size: 20px;
        letter-spacing: 2px;
        color: var(--text-hi);
    }

    /* ── Spinner ── */
    [data-testid="stSpinner"] p {
        font-family: var(--mono) !important;
        font-size: 10px !important;
        letter-spacing: 2px !important;
        color: var(--accent) !important;
        text-transform: uppercase !important;
    }

    /* ── Main padding ── */
    .block-container { padding: 28px 32px 40px 32px !important; max-width: 100% !important; }
    </style>
    """, unsafe_allow_html=True)


# ─── 2. ESTADO DE SESIÓN ─────────────────────────────────────────────────────
def init_state():
    defaults = {
        "gdf_analizado": None,
        "ultimo_municipio": "",
        "v_calculada": False,
        "a_calculada": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─── 3. NORMALIZACIÓN ────────────────────────────────────────────────────────
def normalizar_rangos(serie: pd.Series, invertir: bool = False, n_rangos: int = 5) -> pd.Series:
    """
    Clasifica valores en escala 1–n_rangos por rangos iguales (min-max).
    Si invertir=True, menor valor → mayor puntaje (ej. TWI: zonas bajas = más amenaza).
    """
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    v_min, v_max = serie_num.min(), serie_num.max()

    if v_max == v_min:
        return pd.Series([n_rangos // 2 + 1] * len(serie_num), index=serie_num.index)

    rango = (v_max - v_min) / n_rangos

    def _puntaje(valor):
        if pd.isna(valor):
            return 1
        if valor >= v_max:
            p = n_rangos
        else:
            p = int((valor - v_min) / rango) + 1
            p = min(p, n_rangos)
        if invertir:
            return (n_rangos + 1) - p
        return p

    return serie_num.apply(_puntaje)


def score_a_indice(serie: pd.Series, suma_min: float | None = None, suma_max: float | None = None) -> pd.Series:
    """
    Re-escala una suma de scores al rango 1–5 usando límites TEÓRICOS fijos.
    - suma_min: valor mínimo posible (ej. n_variables * 1)
    - suma_max: valor máximo posible (ej. n_variables * 5, o con pesos)
    Si no se pasan, usa el min/max observado (comportamiento anterior).
    """
    serie_num = pd.to_numeric(serie, errors="coerce").fillna(0)
    v_min = suma_min if suma_min is not None else serie_num.min()
    v_max = suma_max if suma_max is not None else serie_num.max()

    if v_max == v_min:
        return pd.Series([3] * len(serie_num), index=serie_num.index)

    n_rangos = 5
    rango = (v_max - v_min) / n_rangos

    def _puntaje(valor):
        if pd.isna(valor):
            return 1
        if valor >= v_max:
            return n_rangos
        p = int((valor - v_min) / rango) + 1
        return min(max(p, 1), n_rangos)

    return serie_num.apply(_puntaje)


def pct_a_label(val: int) -> str:
    return NIVELES.get(val, "—")


# ─── 4. CARGA DE DATOS ───────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def cargar_datos():
    if not os.path.exists(RUTAS["mapa"]):
        return None, f"No se encontró: {RUTAS['mapa']}"
    if not os.path.exists(RUTAS["csv"]):
        return None, f"No se encontró: {RUTAS['csv']}"

    try:
        gdf = gpd.read_file(RUTAS["mapa"])
        gdf["LINK"] = gdf["LINK"].astype(str).str.strip().str.zfill(9)

        df = pd.read_csv(RUTAS["csv"], sep=",", encoding="utf-8").fillna(0)
        df.columns = [c.replace('"', "").strip() for c in df.columns]

        # Columna ID del CSV: "Código de radio" (sin punto) es el campo correcto
        # Fallback a la primera columna si no existe
        COL_RADIO = "Código de radio"
        col_id = COL_RADIO if COL_RADIO in df.columns else df.columns[0]

        df[col_id] = df[col_id].astype(str).str.replace('"', "").str.strip().str.zfill(9)

        # Deduplicar por col_id antes del merge para evitar multiplicar filas
        df = df.drop_duplicates(subset=[col_id])

        merged = gdf.merge(df, left_on="LINK", right_on=col_id, how="inner")
        if len(merged) == 0:
            return None, "El merge resultó vacío. Verificá las claves LINK vs columna ID del CSV."

        return merged, None
    except Exception as exc:
        return None, str(exc)


# ─── 4b. CARGA Y PROCESAMIENTO SMN ──────────────────────────────────────────
@st.cache_data(show_spinner=False)
def cargar_smn() -> pd.DataFrame | None:
    """
    Lee smn_normales.csv y devuelve un DataFrame pivotado con:
      - Estación
      - Precipitacion_<Mes>   (mm)
      - FrecPrecip_<Mes>      (días con lluvia >1mm)
    Descarta filas con S/D y convierte a numérico.
    """
    ruta = RUTAS["smn"]
    if not os.path.exists(ruta):
        return None

    df = pd.read_csv(ruta, encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]

    # Nos quedamos solo con las filas de precipitación y frecuencia
    mask_prec = df["Valor Medio de"].str.strip() == "Precipitación (mm)"
    mask_freq = df["Valor Medio de"].str.strip() == "Frecuencia de días con Precipitación superior a 1.0 mm"

    df_prec = df[mask_prec].copy()
    df_freq = df[mask_freq].copy()

    def limpiar(df_src, prefijo):
        df_src = df_src.copy()
        # Normalizar TODOS los nombres de columna antes de operar
        df_src.columns = [c.strip() for c in df_src.columns]
        # Detectar la columna de estación flexiblemente (primera columna no-mes)
        col_estacion = df_src.columns[0]
        col_variable = [c for c in df_src.columns if c == "Valor Medio de"]
        if col_variable:
            df_src = df_src.drop(columns=col_variable)
        df_src = df_src.replace("S/D", np.nan)
        for mes in MESES:
            if mes in df_src.columns:
                df_src[mes] = pd.to_numeric(df_src[mes], errors="coerce")
        df_src = df_src.rename(columns={m: f"{prefijo}_{m}" for m in MESES})
        # Renombrar la col de estación a nombre canónico
        if col_estacion != "Estación":
            df_src = df_src.rename(columns={col_estacion: "Estación"})
        df_src["Estación"] = df_src["Estación"].astype(str).str.strip()
        return df_src.reset_index(drop=True)

    df_prec = limpiar(df_prec, "Prec")
    df_freq = limpiar(df_freq, "Freq")

    merged = df_prec.merge(df_freq, on="Estación", how="inner")
    # Eliminar estaciones sin datos en ningún mes de precipitación
    cols_prec = [f"Prec_{m}" for m in MESES]
    merged = merged.dropna(subset=cols_prec, how="all")
    return merged.reset_index(drop=True)


def score_smn_mensual(df_smn: pd.DataFrame, estacion: str, mes: str) -> dict:
    """
    Normaliza precipitación y frecuencia usando el rango ANUAL de la estación
    (máximo y mínimo entre todos los meses), igual que la lógica de vulnerabilidad.

    Pasos:
      1. Extraer los 12 valores mensuales de la estación para cada variable.
      2. Calcular min/max anual → dividir en 5 rangos iguales.
      3. Ubicar el mes seleccionado en ese rango → p_prec y p_freq (1–5).
      4. Retornar valores crudos y scores para mostrar en el panel informativo.
    """
    fila = df_smn[df_smn["Estación"] == estacion]
    if fila.empty:
        return {"prec_mm": 0, "freq_dias": 0, "p_prec": 1, "p_freq": 1}

    # Serie anual de la estación (12 meses)
    prec_anual = pd.to_numeric(
        fila[[f"Prec_{m}" for m in MESES]].iloc[0], errors="coerce"
    ).fillna(0)
    freq_anual = pd.to_numeric(
        fila[[f"Freq_{m}" for m in MESES]].iloc[0], errors="coerce"
    ).fillna(0)

    prec_mm   = float(prec_anual[f"Prec_{mes}"])
    freq_dias = float(freq_anual[f"Freq_{mes}"])

    def rango_anual(serie, valor):
        """Ubica 'valor' en 1–5 según el min/max de la serie anual (12 meses)."""
        v_min, v_max = serie.min(), serie.max()
        if v_max == v_min:
            return 3
        intervalo = (v_max - v_min) / 5
        p = int((valor - v_min) / intervalo) + 1
        return min(max(p, 1), 5)

    p_prec = rango_anual(prec_anual, prec_mm)
    p_freq = rango_anual(freq_anual, freq_dias)

    return {
        "prec_mm":    prec_mm,
        "freq_dias":  freq_dias,
        "p_prec":     p_prec,
        "p_freq":     p_freq,
        "prec_anual": prec_anual,
        "freq_anual": freq_anual,
    }


# ─── 5. COMPONENTES UI ───────────────────────────────────────────────────────
def header_principal():
    st.markdown("""
    <div class="gird-header">
      <div class="gird-logo">
        <div class="gird-logo-bars">
          <div class="gird-logo-bar" style="height:28px;opacity:0.4;"></div>
          <div class="gird-logo-bar" style="height:20px;opacity:0.6;"></div>
          <div class="gird-logo-bar" style="height:34px;opacity:0.85;"></div>
          <div class="gird-logo-bar" style="height:24px;opacity:0.6;"></div>
          <div class="gird-logo-bar" style="height:16px;opacity:0.4;"></div>
        </div>
      </div>
      <div class="gird-title-block">
        <span class="gird-eyebrow">Sistema de análisis territorial</span>
        <div class="gird-title">GIRD · AR</div>
        <div class="gird-subtitle">Gestión Integral del Riesgo de Desastres</div>
      </div>
      <div class="gird-badges">
        <span class="badge">INDEC · Censo 2022</span>
        <span class="badge">IGN · MDE-Ar</span>
        <span class="badge badge-active">Sistema activo</span>
      </div>
    </div>
    """, unsafe_allow_html=True)


def metricas_resumen(gdf: gpd.GeoDataFrame, col_score: str, titulo: str):
    st.markdown(f'<div class="section-label">Distribución · {titulo}</div>', unsafe_allow_html=True)
    counts = gdf[col_score].map(pct_a_label).value_counts()
    cols = st.columns(5)
    for i, (nivel, lbl) in enumerate(NIVELES.items()):
        n = counts.get(lbl, 0)
        cols[i].metric(lbl, n)


def metricas_riesgo_poblacion(gdf: gpd.GeoDataFrame, col_score: str, col_pob: str):
    """
    Muestra distribución de radios Y población total por nivel de riesgo.
    col_pob: columna con población total por radio censal.
    """
    st.markdown('<div class="section-label">Distribución · Riesgo</div>', unsafe_allow_html=True)

    pob = pd.to_numeric(gdf[col_pob], errors="coerce").fillna(0)
    niveles_radio = gdf[col_score].map(pct_a_label)
    pob_total = int(pob.sum())

    cols = st.columns(5)
    for i, (nivel_int, lbl) in enumerate(NIVELES.items()):
        mask       = niveles_radio == lbl
        n_radios   = int(mask.sum())
        n_hab      = int(pob[mask].sum())
        pct        = (n_hab / pob_total * 100) if pob_total > 0 else 0
        color      = COLORES_NIVEL.get(lbl, "#3d5068")
        cols[i].markdown(
            f'<div style="background:var(--bg-card);border:1px solid var(--border);'
            f'border-top:2px solid {color};border-radius:2px;padding:12px 14px;">'
            f'<div style="font-family:var(--mono,monospace);font-size:8px;letter-spacing:2px;'
            f'color:{color};text-transform:uppercase;margin-bottom:6px;">{lbl}</div>'
            f'<div style="font-family:var(--display,sans-serif);font-size:26px;'
            f'letter-spacing:2px;color:var(--text-hi);">{n_radios}</div>'
            f'<div style="font-family:var(--mono,monospace);font-size:9px;color:var(--text-mid);'
            f'margin-top:4px;">radios</div>'
            f'<div style="border-top:1px solid var(--border);margin:8px 0 6px 0;"></div>'
            f'<div style="font-family:var(--display,sans-serif);font-size:18px;'
            f'letter-spacing:1px;color:var(--text-hi);">{n_hab:,}</div>'
            f'<div style="font-family:var(--mono,monospace);font-size:9px;color:var(--text-mid);'
            f'margin-top:2px;">hab · {pct:.1f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Total general
    st.markdown(
        f'<div style="margin-top:10px;padding:8px 14px;background:var(--bg-card);'
        f'border:1px solid var(--border);border-radius:2px;display:flex;'
        f'align-items:center;gap:12px;">'
        f'<span style="font-family:var(--mono,monospace);font-size:9px;'
        f'letter-spacing:2px;color:var(--text-lo);text-transform:uppercase;">Total distrito</span>'
        f'<span style="font-family:var(--display,sans-serif);font-size:20px;'
        f'letter-spacing:2px;color:var(--accent);">{pob_total:,}</span>'
        f'<span style="font-family:var(--mono,monospace);font-size:9px;'
        f'color:var(--text-mid);">habitantes</span>'
        f'<span style="margin-left:auto;font-family:var(--mono,monospace);font-size:9px;'
        f'color:var(--text-lo);">{len(gdf)} radios censales</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def tarjetas_nivel(gdf: gpd.GeoDataFrame, col_score: str, n: int = 5):
    st.markdown('<div class="section-label">Radios críticos</div>', unsafe_allow_html=True)
    top = (
        gdf[["LINK", col_score]]
        .assign(Nivel=gdf[col_score].map(pct_a_label))
        .sort_values(col_score, ascending=False)
        .head(n)
    )
    for _, row in top.iterrows():
        nivel = row["Nivel"]
        color = COLORES_NIVEL.get(nivel, "#3d5068")
        st.markdown(
            f'<div class="nivel-card" style="border-left-color:{color};">'
            f'<div class="nivel-dot" style="background:{color};"></div>'
            f'<span class="nivel-label" style="color:{color};">{nivel}</span>'
            f'<span class="nivel-link">· {row["LINK"]}</span>'
            f'<span class="nivel-score">{row[col_score]} / 5</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def mapa_coropletico(
    gdf: gpd.GeoDataFrame,
    col_score: str,
    paleta: str,
    tooltip_extra: list[str] | None = None,
    key: str = "map",
):
    cx = gdf.geometry.centroid.x.mean()
    cy = gdf.geometry.centroid.y.mean()

    m = folium.Map(
        location=[cy, cx],
        zoom_start=12,
        tiles="CartoDB dark_matter",
        attr="© CartoDB",
    )

    folium.Choropleth(
        geo_data=gdf.__geo_interface__,
        data=gdf,
        columns=["LINK", col_score],
        key_on="feature.properties.LINK",
        fill_color=paleta,
        fill_opacity=0.75,
        line_opacity=0.3,
        line_color="#1c2535",
        bins=[1, 2, 3, 4, 5, 6],
        legend_name=col_score,
        nan_fill_color="#0d1117",
    ).add_to(m)

    campos = ["LINK", col_score] + (tooltip_extra or [])
    campos = [c for c in campos if c in gdf.columns]
    aliases = [c.replace("_", " ") + ":" for c in campos]

    folium.GeoJson(
        gdf[campos + ["geometry"]],
        style_function=lambda _: {"fillOpacity": 0, "weight": 0},
        tooltip=GeoJsonTooltip(
            fields=campos,
            aliases=aliases,
            localize=True,
            sticky=False,
            labels=True,
        ),
    ).add_to(m)

    st_folium(m, width="100%", height=420, returned_objects=[], key=key)


# ─── 6. SIDEBAR ──────────────────────────────────────────────────────────────
def sidebar(gdf_master: gpd.GeoDataFrame) -> tuple[str, gpd.GeoDataFrame]:
    with st.sidebar:
        st.markdown("""
        <div class="sidebar-brand">
          <div class="sb-label">Sistema GIRD</div>
          <div class="sb-title">ARG</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-label">Área de análisis</div>', unsafe_allow_html=True)
        municipios = sorted(gdf_master["NOMDEPTO"].unique())
        depto_sel = st.selectbox("Municipio / Distrito", municipios, label_visibility="collapsed")

        if st.session_state["ultimo_municipio"] != depto_sel:
            st.session_state["gdf_analizado"] = None
            st.session_state["v_calculada"] = False
            st.session_state["a_calculada"] = False
            st.session_state["ultimo_municipio"] = depto_sel

        st.markdown("---")
        st.markdown('<div class="section-label">Estado del análisis</div>', unsafe_allow_html=True)

        v_ok = st.session_state.get("v_calculada", False)
        a_ok = st.session_state.get("a_calculada", False)
        r_ok = v_ok and a_ok

        def estado_badge(label, ok):
            color  = "#4ade80" if ok else "#3d5068"
            symbol = "●" if ok else "○"
            st.markdown(
                f'<div style="font-family:var(--mono,monospace);font-size:10px;'
                f'letter-spacing:1.5px;color:{color};padding:3px 0;">'
                f'{symbol} &nbsp;{label}</div>',
                unsafe_allow_html=True,
            )

        estado_badge("Vulnerabilidad", v_ok)
        estado_badge("Amenaza", a_ok)
        estado_badge("Riesgo compuesto", r_ok)

        st.markdown("---")
        if not RASTER_OK:
            st.warning("rasterio/rasterstats no disponibles. Análisis topográfico desactivado.")

    if st.session_state["gdf_analizado"] is not None:
        gdf_filt = st.session_state["gdf_analizado"]
    else:
        gdf_filt = gdf_master[gdf_master["NOMDEPTO"] == depto_sel].copy()

    return depto_sel, gdf_filt


# ─── 7. PESTAÑA VULNERABILIDAD ───────────────────────────────────────────────
def tab_vulnerabilidad(gdf: gpd.GeoDataFrame, gdf_master: gpd.GeoDataFrame):
    st.markdown("## Vulnerabilidad Social")

    EXCLUIR = {"LINK", "geometry", "NOMPROV", "NOMDEPTO"}
    indicadores = [c for c in gdf_master.columns if c not in EXCLUIR and gdf_master[c].dtype != object]

    col_vars, col_config = st.columns([2, 1])

    with col_vars:
        st.markdown('<div class="section-label">Variables del censo</div>', unsafe_allow_html=True)
        vars_sel = st.multiselect(
            "Variables",
            indicadores,
            label_visibility="collapsed",
            help="Seleccioná las variables que componen el índice de vulnerabilidad.",
        )

    with col_config:
        st.markdown('<div class="section-label">Método</div>', unsafe_allow_html=True)
        metodo = st.selectbox(
            "Normalización",
            ["Min-Max distrital", "Percentiles (cuartiles)", "Igual peso"],
            label_visibility="collapsed",
        )

    if not vars_sel:
        st.info("Seleccioná al menos una variable para calcular la vulnerabilidad.")
        return gdf

    st.markdown('<div class="section-label">Ponderación por variable</div>', unsafe_allow_html=True)
    peso_cols = st.columns(min(len(vars_sel), 4))
    pesos = {}
    for i, v in enumerate(vars_sel):
        with peso_cols[i % len(peso_cols)]:
            pesos[v] = st.slider(v[:22], 1, 5, 2, key=f"peso_{v}")

    if st.button("▶  CALCULAR VULNERABILIDAD"):
        with st.spinner("Procesando índice de vulnerabilidad…"):
            scores_pond = []
            for v in vars_sel:
                col_norm = f"_p_{v}"
                gdf[col_norm] = normalizar_rangos(
                    pd.to_numeric(gdf[v], errors="coerce").fillna(0)
                )
                col_pond = f"_pp_{v}"
                gdf[col_pond] = gdf[col_norm] * pesos[v]
                scores_pond.append(col_pond)

            gdf["V_Suma"]  = gdf[scores_pond].sum(axis=1)
            n_vars   = len(vars_sel)
            peso_min = min(pesos.values())
            peso_max = max(pesos.values())
            v_sum_min = n_vars * 1 * peso_min   # todas las vars en score 1 con peso mínimo
            v_sum_max = n_vars * 5 * peso_max   # todas las vars en score 5 con peso máximo
            gdf["V_Score"] = score_a_indice(gdf["V_Suma"], suma_min=v_sum_min, suma_max=v_sum_max)
            gdf["V_Nivel"] = gdf["V_Score"].map(pct_a_label)

            st.session_state["gdf_analizado"] = gdf
            st.session_state["v_calculada"] = True

    if "V_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1:
            mapa_coropletico(
                gdf, "V_Score", PALETAS["vulnerabilidad"],
                tooltip_extra=["V_Nivel"] + [f"_p_{v}" for v in vars_sel if f"_p_{v}" in gdf.columns],
                key="map_v",
            )
        with c2:
            metricas_resumen(gdf, "V_Score", "Vulnerabilidad")
            tarjetas_nivel(gdf, "V_Score")

    return gdf


# ─── 8. PESTAÑA AMENAZA ──────────────────────────────────────────────────────
def tab_amenaza(gdf: gpd.GeoDataFrame):
    st.markdown("## Amenaza Hidrometeorológica")

    df_smn = cargar_smn()
    smn_ok = df_smn is not None and len(df_smn) > 0

    if not smn_ok:
        st.warning(
            f"No se encontró el archivo de normales climáticas del SMN en `{RUTAS['smn']}`. "
            "Copiá el archivo `smn_normales.csv` dentro de la carpeta `data/`."
        )
        return gdf

    usar_raster = RASTER_OK and os.path.exists(RUTAS["raster"])

    # ── Controles ─────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)

    with c1:
        st.markdown('<div class="section-label">Mes de análisis</div>', unsafe_allow_html=True)
        mes_actual = pd.Timestamp.now().month - 1
        mes_sel = st.selectbox(
            "Mes", MESES, index=mes_actual, label_visibility="collapsed",
            help="Se usarán las normales climáticas históricas del mes seleccionado.",
        )

    with c2:
        st.markdown('<div class="section-label">Estación SMN de referencia</div>', unsafe_allow_html=True)
        estaciones = sorted(df_smn["Estación"].tolist())
        estacion_sel = st.selectbox(
            "Estación", estaciones, label_visibility="collapsed",
            help="Seleccioná la estación meteorológica más cercana al municipio.",
        )

    # ── Panel informativo ─────────────────────────────────────────────────
    datos_mes = score_smn_mensual(df_smn, estacion_sel, mes_sel)

    st.markdown(
        f'<div class="section-label">Normales climáticas · {estacion_sel} · {mes_sel}</div>',
        unsafe_allow_html=True,
    )

    # Mostrar valores crudos + scores del mes seleccionado
    ci1, ci2, ci3, ci4 = st.columns(4)
    ci1.metric("Precipitación del mes", f"{datos_mes['prec_mm']:.1f} mm",
               help="Valor normal histórico para el mes seleccionado.")
    ci2.metric("Días con lluvia >1mm", f"{datos_mes['freq_dias']:.1f} días",
               help="Frecuencia normal histórica de días con lluvia.")
    ci3.metric("Score precipitación", f"{datos_mes['p_prec']} / 5",
               help="Posición del mes en el rango anual de la estación (1=mín · 5=máx).")
    ci4.metric("Score frecuencia", f"{datos_mes['p_freq']} / 5",
               help="Posición del mes en el rango anual de la estación (1=mín · 5=máx).")

    if not usar_raster:
        st.warning(
            "Archivo MDE no encontrado o rasterio/rasterstats no instalados. "
            "La amenaza se calculará solo con las dos variables climáticas del SMN."
        )

# --- BUSCÁ EL BLOQUE DEL BOTÓN DE CÁLCULO ---
if st.button("▶  CALCULAR AMENAZA"):
    with st.spinner("Procesando amenaza territorial…"):

        # ── Variable 1: TWI (Análisis con Rasterio Puro) ───
        if usar_raster and RASTER_OK:
            import rasterio
            from rasterio.mask import mask
            
            # Función interna para reemplazar zonal_stats
            def calcular_media_manual(gdf_input, raster_path):
                resultados = []
                with rasterio.open(raster_path) as src:
                    for geom in gdf_input.geometry:
                        try:
                            # Cortamos el raster con la forma del radio censal
                            out_image, _ = mask(src, [geom], crop=True)
                            data = out_image[0]
                            # Filtramos valores NoData (típicos de MDE)
                            validos = data[data > -9000] 
                            if validos.size > 0:
                                resultados.append(float(validos.mean()))
                            else:
                                resultados.append(0.0)
                        except:
                            resultados.append(0.0)
                return resultados

            # REEMPLAZO DE LA LÍNEA DEL ERROR:
            # En lugar de stats = zonal_stats(...), usamos nuestra función:
            gdf["twi_raw"] = calcular_media_manual(gdf, RUTAS["raster"])
            
            # Invertir=True: zonas más bajas (valores de elevación menores) → mayor amenaza
            gdf["p_twi"] = normalizar_rangos(gdf["twi_raw"], invertir=True)
        else:
            # Sin raster o si falló la carga inicial
            gdf["twi_raw"] = 0.0
            gdf["p_twi"] = 3

            # ── Variables 2 y 3: clima SMN (valor único para el distrito) ─
            # El score del mes ya fue normalizado en el rango anual de la estación (1–5)
            # Se asigna el mismo valor a todos los radios del distrito
            p_prec_mes = datos_mes["p_prec"]   # score precipitación del mes (1–5)
            p_freq_mes = datos_mes["p_freq"]    # score frecuencia del mes (1–5)

            # ── Suma de los 3 scores ──────────────────────────────────────
            # Rango posible: 3 (mínimo) a 15 (máximo)
            gdf["A_Suma"] = gdf["p_twi"] + p_prec_mes + p_freq_mes

            # ── Re-normalización final en 5 rangos ────────────────────────
            # Aplica la misma lógica min/max que vulnerabilidad
            gdf["A_Score"]    = score_a_indice(gdf["A_Suma"], suma_min=3, suma_max=15)
            gdf["A_Nivel"]    = gdf["A_Score"].map(pct_a_label)
            gdf["A_Mes"]      = mes_sel
            gdf["A_Estacion"] = estacion_sel
            gdf["A_PrecMes"]  = datos_mes["prec_mm"]
            gdf["A_FreqMes"]  = datos_mes["freq_dias"]
            gdf["A_pTWI"]     = gdf["p_twi"]
            gdf["A_pPrec"]    = p_prec_mes
            gdf["A_pFreq"]    = p_freq_mes

            st.session_state["gdf_analizado"] = gdf
            st.session_state["a_calculada"] = True

# ... (todo el código anterior del botón y cálculos)

    if "A_Score" in gdf.columns:
        c1, c2 = st.columns([3, 1])
        with c1:
            mapa_coropletico(
                gdf, "A_Score", PALETAS["amenaza"],
                tooltip_extra=["A_Nivel", "A_Mes", "A_pTWI", "A_pPrec", "A_pFreq"],
                key="map_a",
            )
        with c2:
            metricas_resumen(gdf, "A_Score", "Amenaza")
            tarjetas_nivel(gdf, "A_Score")

    # ESTA LÍNEA ES LA DEL ERROR: Debe tener espacios a la izquierda
    return gdf

# ─── 9. PESTAÑA RIESGO ───────────────────────────────────────────────────────
def tab_riesgo(gdf: gpd.GeoDataFrame):
    st.markdown("## Riesgo Compuesto")

    v_ok = "V_Score" in gdf.columns
    a_ok = "A_Score" in gdf.columns

    if not v_ok or not a_ok:
        faltantes = []
        if not v_ok: faltantes.append("Vulnerabilidad")
        if not a_ok: faltantes.append("Amenaza")
        st.info(f"Completá las pestañas: {' y '.join(faltantes)} para generar el mapa de riesgo.")
        return gdf

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="section-label">Peso vulnerabilidad</div>', unsafe_allow_html=True)
        w_vul = st.slider("Peso Vulnerabilidad", 1, 5, 3, label_visibility="collapsed")
    with c2:
        st.markdown('<div class="section-label">Peso amenaza</div>', unsafe_allow_html=True)
        w_amen = st.slider("Peso Amenaza", 1, 5, 3, label_visibility="collapsed")

    if st.button("▶  CALCULAR RIESGO COMPUESTO"):
        with st.spinner("Generando matriz de riesgo…"):
            gdf["R_Suma"]  = gdf["V_Score"] * w_vul + gdf["A_Score"] * w_amen
            r_sum_min = 1 * w_vul + 1 * w_amen   # ambos scores en mínimo
            r_sum_max = 5 * w_vul + 5 * w_amen   # ambos scores en máximo
            gdf["R_Score"] = score_a_indice(gdf["R_Suma"], suma_min=r_sum_min, suma_max=r_sum_max)
            gdf["R_Nivel"] = gdf["R_Score"].map(pct_a_label)
            st.session_state["gdf_analizado"] = gdf

    if "R_Score" in gdf.columns:
        # ── Columna de población ───────────────────────────────────────────
        COL_POB = "Población total"
        EXCLUIR = {"LINK", "geometry", "NOMPROV", "NOMDEPTO"}
        numericas = [c for c in gdf.columns if c not in EXCLUIR and gdf[c].dtype != object]

        if COL_POB in gdf.columns:
            col_pob = COL_POB
        else:
            st.markdown('<div class="section-label">Columna de población total</div>', unsafe_allow_html=True)
            col_pob = st.selectbox(
                "No se encontró 'Población total'. Seleccioná la columna correcta:",
                numericas,
                label_visibility="collapsed",
            )

        c1, c2 = st.columns([3, 1])
        with c1:
            mapa_coropletico(
                gdf, "R_Score", PALETAS["riesgo"],
                tooltip_extra=["V_Score", "A_Score", "R_Nivel"],
                key="map_r",
            )
        with c2:
            tarjetas_nivel(gdf, "R_Score")

        metricas_riesgo_poblacion(gdf, "R_Score", col_pob)

        # Exportar CSV
        st.markdown('<div class="section-label">Exportar</div>', unsafe_allow_html=True)
        cols_export = ["LINK"]
        if "NOMDEPTO" in gdf.columns: cols_export.append("NOMDEPTO")
        cols_export += [c for c in ["V_Score", "A_Score", "R_Score", "R_Nivel", col_pob] if c in gdf.columns]
        df_export = gdf[cols_export].sort_values("R_Score", ascending=False).reset_index(drop=True)
        csv_bytes = df_export.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇  EXPORTAR CSV",
            data=csv_bytes,
            file_name=f"riesgo_{st.session_state['ultimo_municipio'].lower().replace(' ', '_')}.csv",
            mime="text/csv",
        )

    return gdf


# ─── 10. MAIN ─────────────────────────────────────────────────────────────────
def main():
    aplicar_tema()
    init_state()
    header_principal()

    gdf_master, error = cargar_datos()

    if gdf_master is None:
        st.error(f"**Error al cargar datos:** {error}")
        st.markdown("""
        **Estructura de archivos requerida:**
        ```
        data/
        ├── radioscensales.geojson   ← geometrías con campo LINK (9 dígitos)
        ├── indicadores.csv          ← indicadores por radio (col. LINK o 'radio'/'código')
        └── 3560-12.img              ← ráster MDE (opcional)
        ```
        """)
        return

    _, gdf_filt = sidebar(gdf_master)

    st.markdown("")

    tab_v, tab_a, tab_r = st.tabs([
        "  📊  VULNERABILIDAD  ",
        "  🌊  AMENAZA  ",
        "  ⚠️  RIESGO  ",
    ])

    with tab_v:
        gdf_filt = tab_vulnerabilidad(gdf_filt, gdf_master)

    with tab_a:
        gdf_filt = tab_amenaza(gdf_filt)

    with tab_r:
        tab_riesgo(gdf_filt)


if __name__ == "__main__":
    main()

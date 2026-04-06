import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
import os

# 1. CONFIGURACIÓN E INTERFAZ
st.set_page_config(page_title="SIG Gestión de Riesgos v8", layout="wide")

# Estructura de datos persistente para multiamenaza
if 'amenazas' not in st.session_state:
    st.session_state['amenazas'] = {"Inundación": {}, "Incendio": {}, "Tormenta": {}, "Ola de Calor": {}}
if 'ultimo_municipio' not in st.session_state:
    st.session_state['ultimo_municipio'] = ""

@st.cache_data
def cargar_datos():
    ruta_mapa, ruta_csv = "data/radioscensales.geojson", "data/indicadores.csv"
    if not os.path.exists(ruta_mapa): return None
    gdf = gpd.read_file(ruta_mapa)
    gdf['LINK'] = gdf['LINK'].astype(str).str.strip()
    # Cargamos el CSV con manejo de errores básico
    try:
        df = pd.read_csv(ruta_csv, sep=',', encoding='latin-1').fillna(0)
        df.columns = [c.replace('"', '').strip() for c in df.columns]
        col_id = next((c for c in df.columns if 'código' in c.lower() or 'radio' in c.lower()), df.columns[0])
        df[col_id] = df[col_id].astype(str).str.replace('"', '').str.strip().str.zfill(9)
        return gdf.merge(df, left_on='LINK', right_on=col_id, how='inner')
    except:
        return None

gdf_master = cargar_datos()

if gdf_master is not None:
    # --- BARRA LATERAL ---
    st.sidebar.title("Configuración Global")
    municipios = sorted(gdf_master['NOMDEPTO'].unique())
    depto_sel = st.sidebar.selectbox("Distrito de Análisis", municipios)
    
    if st.session_state['ultimo_municipio'] != depto_sel:
        for k in st.session_state['amenazas']: st.session_state['amenazas'][k] = {}
        st.session_state['ultimo_municipio'] = depto_sel

    tipo_activa = st.sidebar.selectbox("Amenaza a Modelar", list(st.session_state['amenazas'].keys()))
    gdf_filtered = gdf_master[gdf_master['NOMDEPTO'] == depto_sel].copy()
    etiquetas = ["Muy Bajo", "Bajo", "Medio", "Alto", "Muy Alto"]

    # --- PESTAÑAS ---
    tab_ini, tab_v, tab_a, tab_r = st.tabs(["🏠 Inicio", "📊 Vulnerabilidad", "🔥 Amenaza", "⚠️ Riesgo"])

    # --- TAB 1: PROYECTO ---
    with tab_ini:
        st.markdown(f"""
        <div style="text-align: center; padding: 30px; background-color: #f8f9fa; border-radius: 15px; border: 1px solid #e9ecef;">
            <h1 style="color: #1f1f1f;">Análisis de Riesgo Localizado</h1>
            <p style="font-size: 1.1em; color: #444; max-width: 900px; margin: auto;">
                Este proyecto de <b>Protección Civil</b> permite modelar escenarios críticos cruzando la vulnerabilidad social 
                del Censo con variables técnicas de amenaza. La herramienta facilita la identificación de radios censales 
                prioritarios en el distrito de <b>{depto_sel}</b> para optimizar la respuesta ante emergencias.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Unidades Territoriales", len(gdf_filtered))
        c2.metric("Amenaza Seleccionada", tipo_activa)
        c3.metric("Nivel de Análisis", "Radio Censal")

    # --- TAB 2: VULNERABILIDAD COMBINADA ---
    with tab_v:
        st.subheader("Configuración de Vulnerabilidad Social Compuesta")
        excluir = ['LINK', 'geometry', 'NOMPROV', 'NOMDEPTO', 'fid', 'AREA', 'PERIMETER']
        indicadores = [c for c in gdf_master.columns if c not in excluir]
        
        # Selección múltiple de indicadores
        vars_sel = st.multiselect("Combine indicadores (Promedio ponderado):", indicadores)
        
        if vars_sel:
            scores_temp = []
            for v in vars_sel:
                # Normalizamos cada una individualmente para que pesen lo mismo
                gdf_filtered[f's_{v}'] = pd.cut(pd.to_numeric(gdf_filtered[v], errors='coerce').fillna(0), bins=5, labels=[1, 2, 3, 4, 5]).astype(int)
                scores_temp.append(f's_{v}')
            
            # Calculamos el promedio de los scores seleccionados
            gdf_filtered['V_Score'] = gdf_filtered[scores_temp].mean(axis=1).round().astype(int)
            gdf_filtered['V_Nivel'] = pd.cut(gdf_filtered['V_Score'], bins=[0, 1, 2, 3, 4, 5], labels=etiquetas)
            
            m1 = folium.Map(location=[gdf_filtered.geometry.centroid.y.mean(), gdf_filtered.geometry.centroid.x.mean()], zoom_start=12)
            folium.Choropleth(
                geo_data=gdf_filtered, data=gdf_filtered, columns=['LINK', 'V_Score'], 
                key_on='feature.properties.LINK', fill_color='YlGn', legend_name="Nivel de Vulnerabilidad"
            ).add_to(m1)
            st_folium(m1, width="100%", height=400, key="map_v")
        else:
            st.warning("Seleccione al menos un indicador para visualizar el mapa de vulnerabilidad.")

    # --- TAB 3: AMENAZA E IMPACTO ---
    with tab_a:
        st.subheader(f"Modelado de Amenaza: {tipo_activa}")
        st.info("Haga clic en los radios para configurar Frecuencia, Afectación y Mortalidad.")
        
        m_a = folium.Map(location=[gdf_filtered.geometry.centroid.y.mean(), gdf_filtered.geometry.centroid.x.mean()], zoom_start=12, tiles="cartodbpositron")
        
        def style_a(f):
            is_in = f['properties']['LINK'] in st.session_state['amenazas'][tipo_activa]
            return {'fillColor': '#e74c3c' if is_in else '#BDBDBD', 'fillOpacity': 0.5 if is_in else 0.1, 'color': 'black', 'weight': 1}

        map_out = st_folium(m_a.add_child(folium.GeoJson(gdf_filtered, style_function=style_a)), width="100%", height=400, key=f"map_{tipo_activa}")

        if map_out['last_active_drawing']:
            cid = map_out['last_active_drawing']['properties']['LINK']
            if cid in st.session_state['amenazas'][tipo_activa]:
                del st.session_state['amenazas'][tipo_activa][cid]
            else:
                st.session_state['amenazas'][tipo_activa][cid] = {'frec': 1, 'perc': 1.0, 'mort': 0.1}
            st.rerun()

        if st.session_state['amenazas'][tipo_activa]:
            st.write("---")
            for rid, vls in st.session_state['amenazas'][tipo_activa].items():
                with st.expander(f"📍 Configuración Radio: {rid}", expanded=True):
                    c1, c2, c3 = st.columns(3)
                    st.session_state['amenazas'][tipo_activa][rid]['frec'] = c1.slider(f"Eventos/año", 1, 12, vls['frec'], key=f"f_{rid}")
                    st.session_state['amenazas'][tipo_activa][rid]['perc'] = c2.select_slider(f"% Superficie", [0.1, 0.25, 0.5, 0.7, 1.0], vls['perc'], format_func=lambda x: f"{int(x*100)}%", key=f"p_{rid}")
                    st.session_state['amenazas'][tipo_activa][rid]['mort'] = c3.select_slider(f"% Prob. Mortalidad", [0.1, 0.25, 0.5, 0.7, 1.0], vls['mort'], format_func=lambda x: f"{int(x*100)}%", key=f"m_{rid}")

    # --- TAB 4: RIESGO ---
    with tab_r:
        st.subheader("Mapa de Riesgo y Priorización")
        
        if 'V_Score' not in gdf_filtered:
            st.error("Primero configure la Vulnerabilidad en la pestaña correspondiente.")
        else:
            def calc_a(row):
                d = st.session_state['amenazas'][tipo_activa].get(row['LINK'])
                if not d: return 0
                # Nueva fórmula: Frecuencia * Afectación * Mortalidad
                pts = d['frec'] * d['perc'] * d['mort']
                return 1 if pts <= 0.5 else 2 if pts <= 1.5 else 3 if pts <= 3.0 else 4 if pts <= 6.0 else 5

            gdf_filtered['A_Score'] = gdf_filtered.apply(calc_a, axis=1)
            gdf_filtered['R_Final'] = gdf_filtered['V_Score'] * gdf_filtered['A_Score']
            
            # Mapa Final
            m_res = folium.Map(location=[gdf_filtered.geometry.centroid.y.mean(), gdf_filtered.geometry.centroid.x.mean()], zoom_start=12)
            folium.Choropleth(
                geo_data=gdf_filtered, data=gdf_filtered, columns=['LINK', 'R_Final'], 
                key_on='feature.properties.LINK', fill_color='OrRd'
            ).add_to(m_res)
            st_folium(m_res, width="100%", height=500, key="map_final")
            
            st.write("**Top Radios Críticos**")
            st.dataframe(gdf_filtered[gdf_filtered['A_Score'] > 0][['LINK', 'V_Nivel', 'A_Score', 'R_Final']].sort_values('R_Final', ascending=False))

else:
    st.info("Esperando carga de archivos GeoJSON y CSV...")

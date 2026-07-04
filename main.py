import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, re, pandas as pd
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF

# --- API KEY ---
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE SICURA GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        # Legge il foglio 'ispezioni'
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        # Se il foglio è nuovo o non configurato, crea la struttura
        df_iniziale = pd.DataFrame([{"Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for t in TARGHE_GSSA])
        return df_iniziale

# --- LOGICA ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
df = carica_dati()

menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Area Admin"])

if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia")
    targa = st.selectbox("Seleziona Targa:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video", type=["mp4", "mov"])
    
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi e salvataggio su Cloud..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                
                # Estrazione frame e analisi IA (Codice precedente)
                model = genai.GenerativeModel("gemini-1.5-flash")
                cap = cv2.VideoCapture("temp.mp4")
                ret, frame = cap.read()
                cap.release()
                
                if ret:
                    _, buffer = cv2.imencode('.jpg', frame)
                    response = model.generate_content(["Analizza danni per " + targa, {"mime_type": "image/jpeg", "data": buffer.tobytes()}])
                    ris = response.text
                    
                    # AGGIORNAMENTO DATI
                    df.loc[df["Targa"] == targa, "Report"] = ris
                    df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["Targa"] == targa, "Stato"] = "🚨 ANALIZZATO"
                    
                    # SALVATAGGIO REALE SU GOOGLE SHEETS
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Tutto salvato correttamente su Google Sheets!")
                    st.write(ris)
                else:
                    st.error("Errore nel video.")

elif menu == "👑 Area Admin":
    st.title("Pannello Admin")
    st.dataframe(df)

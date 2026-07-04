import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, re, pandas as pd
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF

# --- CONFIGURAZIONE SISTEMA 2026 ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=API_KEY)

@st.cache_resource
def seleziona_modello_avanzato():
    """Trova e seleziona i modelli 3.5, 3.0 o 2.5 disponibili nell'account"""
    try:
        modelli_disponibili = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Ordine di priorità per il 2026
        ordine_priorita = ["3.5", "3.1", "3.0", "2.5", "2.0"]
        
        for versione in ordine_priorita:
            for m in modelli_disponibili:
                if versione in m:
                    return m
        return modelli_disponibili[0] # Fallback sull'ultimo disponibile
    except Exception:
        return "models/gemini-2.0-flash" # Fallback minimo di sicurezza

MODELLO_TOP = seleziona_modello_avanzato()

TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE DATABASE GOOGLE ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        return pd.DataFrame([{"Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for t in TARGHE_GSSA])

def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 50) 
    for i in range(50):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        # Risoluzione HD per modelli 3.x
        frame_res = cv2.resize(frame, (1024, 768))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frames.append({"mime_type": "image/jpeg", "data": buffer.tobytes()})
    cap.release()
    return frames

def genera_pdf(targa, testo, e_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"CERTIFICATO DI PERIZIA - {targa}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(255, 230, 230) if e_nuovo else pdf.set_fill_color(230, 255, 230)
    testo_esito = "RILEVATI NUOVI DANNI" if e_nuovo else "NESSUN NUOVO DANNO RILEVATO"
    pdf.cell(0, 12, testo_esito, ln=True, fill=True, align="C")
    pdf.ln(5); pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 7, testo.encode('latin-1', 'replace').decode('latin-1'))
    return pdf.output(dest='S')

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO 2026", layout="wide")
df = carica_dati()

st.sidebar.title("💎 GSSA PRO v3.5")
menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia Intelligente")
    st.info(f"Modello AI in funzione: {MODELLO_TOP.split('/')[-1]}")
    targa = st.selectbox("Seleziona Targa:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video Ispezione", type=["mp4", "mov"])
    
    if st.button("🚀 AVVIA ANALISI PROFONDA"):
        if video:
            with st.spinner("L'intelligenza artificiale sta analizzando ogni fotogramma..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                immagini = estrai_frame("temp.mp4")
                
                # Storico da Google Sheets
                row = df[df["Targa"] == targa].iloc[0]
                storico = str(row["Report"]) if pd.notna(row["Report"]) else ""

                # Configurazione Modello 3.x / 2.x
                model = genai.GenerativeModel(
                    model_name=MODELLO_TOP,
                    generation_config={"temperature": 0.1, "max_output_tokens": 8192}
                )
                
                prompt = (f"Sei un perito automobilistico pignolo nel 2026. Veicolo {targa}.\n"
                          f"STORICO PRECEDENTE: {storico}\n"
                          "Analizza le immagini. Se non vedi NUOVI danni rispetto allo storico, "
                          "rispondi esattamente: 'NESSUN NUOVO DANNO'.\n"
                          "Se vedi nuovi danni, elenca solo le novità in modo dettagliato per zona.")

                try:
                    # Chiamata di nuova generazione
                    response = model.generate_content(
                        [prompt] + immagini,
                        safety_settings={
                            'HATE': 'BLOCK_NONE', 'HARASSMENT': 'BLOCK_NONE',
                            'SEXUAL': 'BLOCK_NONE', 'DANGEROUS': 'BLOCK_NONE'
                        }
                    )
                    
                    # Estrazione testo per modelli 2026
                    if response.candidates:
                        ris_ai = response.candidates[0].content.parts[0].text.strip()
                    else:
                        ris_ai = "NESSUN NUOVO DANNO"

                    is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    testo_output = ris_ai if is_nuovo or storico == "" else "✅ Ispezione apposto, nessun nuovo danno rilevato."
                    
                    # Sincronizzazione Google Sheets
                    if is_nuovo or storico == "":
                        df.loc[df["Targa"] == targa, "Report"] = ris_ai
                    df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["Targa"] == targa, "Stato"] = "🚨 DANNI" if is_nuovo else "✅ OK"
                    
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Analisi salvata nel Cloud!")
                    st.markdown(testo_output)
                    
                    pdf_data = genera_pdf(targa, testo_output, is_nuovo)
                    st.download_button("📥 Scarica Report PDF", data=bytes(pdf_data), file_name=f"Perizia_{targa}.pdf")

                except Exception as e:
                    st.error(f"Errore critico AI: {e}")
        else: st.warning("Carica un video.")

elif menu == "👑 Admin":
    st.title("Area Amministratore")
    pw = st.text_input("Password Admin", type="password")
    if pw == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

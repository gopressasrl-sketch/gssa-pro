import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, re, pandas as pd, json
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF

# --- CONFIGURAZIONE CHIAVE API (DA SECRETS) ---
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

# --- FUNZIONE AUTO-SELEZIONE MODELLO (PER EVITARE NOT FOUND) ---
@st.cache_resource
def ottieni_miglior_modello():
    try:
        modelli_validi = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods and "gemini" in m.name:
                modelli_validi.append(m.name)
        if not modelli_validi: return "models/gemini-1.5-flash"
        # Ordina per versione (es. 3.5 > 2.0 > 1.5)
        modelli_validi.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)], reverse=True)
        return modelli_validi[0]
    except:
        return "models/gemini-1.5-flash"

MODELLO_ATTIVO = ottieni_miglior_modello()

# --- LISTA TARGHE UFFICIALE GSSA ---
TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE SICURA GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        df_iniziale = pd.DataFrame([{"Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for t in TARGHE_GSSA])
        return df_iniziale

# --- ELABORAZIONE VIDEO ---
def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    num_da_estrarre = 50 
    step = max(1, total_frames // num_da_estrarre)
    for i in range(num_da_estrarre):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        frame_res = cv2.resize(frame, (1024, 768))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 80])
        frames.append({"image": cv2.cvtColor(frame_res, cv2.COLOR_BGR2RGB), "bytes": buffer.tobytes()})
    cap.release()
    return frames

# --- GENERAZIONE PDF ---
def crea_pdf_report(targa, report_testo, esito_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA VEICOLO: {targa}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 10, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    if esito_nuovo:
        pdf.set_fill_color(255, 230, 230)
        testo_box = "ESITO: RILEVATI DANNI / VARIAZIONI"
    else:
        pdf.set_fill_color(230, 255, 230)
        testo_box = "ESITO: NESSUNA NUOVA ANOMALIA"
    pdf.cell(0, 10, testo_box, ln=True, align="C", fill=True)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    testo_pulito = report_testo.replace("**", "").replace("#", "").encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, testo_pulito)
    return pdf.output(dest='S')

# --- INTERFACCIA UTENTE ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
df = carica_dati()

menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Area Admin"])

if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia con Google Sheets")
    targa = st.selectbox("Seleziona Targa:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video Ispezione", type=["mp4", "mov", "avi"])
    
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner(f"Analisi con {MODELLO_ATTIVO.split('/')[-1]} in corso..."):
                with open("temp_v.mp4", "wb") as f: f.write(video.read())
                frames_estratti = estrai_frame("temp_v.mp4")
                
                # Cerca lo storico nel foglio
                row = df[df["Targa"] == targa].iloc[0]
                storico = str(row["Report"]) if pd.notna(row["Report"]) and row["Report"] != "" else "Nessuno"
                
                model = genai.GenerativeModel(MODELLO_ATTIVO)
                
                # Prompt professionale a zone
                prompt = (f"REPORT PERIZIA - VEICOLO {targa}\n"
                          f"STORICO PRECEDENTE: {storico}\n"
                          "Analizza i 50 frame. ELENCA SOLO I NUOVI DANNI UNICI (Foto: X). "
                          "Se non ci sono nuovi danni rispetto allo storico, rispondi 'NESSUN NUOVO DANNO'. "
                          "Dividi per zone. No introduzioni.")

                contenuto = [{"mime_type": "image/jpeg", "data": f['bytes']} for f in frames_estratti]
                
                try:
                    response = model.generate_content([prompt] + contenuto)
                    ris_ai = response.text.strip()
                    
                    nuovi = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    testo_final = ris_ai if nuovi or storico == "Nessuno" else "✅ Ispezione apposto, nessun nuovo danno rilevato."
                    
                    # Aggiorna il DataFrame
                    if nuovi or storico == "Nessuno":
                        df.loc[df["Targa"] == targa, "Report"] = ris_ai
                    df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["Targa"] == targa, "Stato"] = "🚨 DANNI" if nuovi or storico == "Nessuno" else "✅ OK"
                    
                    # SALVA SU GOOGLE SHEETS
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Analisi salvata su Google Sheets!")
                    
                    st.markdown(testo_final)
                    
                    # Tasto PDF
                    pdf_data = crea_pdf_report(targa, testo_final, nuovi or storico == "Nessuno")
                    st.download_button("📥 SCARICA PDF", data=bytes(pdf_data) if isinstance(pdf_data, (bytes, bytearray)) else pdf_data.encode('latin-1'), file_name=f"Report_{targa}.pdf")
                    
                    # Galleria Mobile
                    st.divider()
                    cols = st.columns(2)
                    for i, f in enumerate(frames_estratti[:10]):
                        with cols[i%2]: st.image(f['image'], use_container_width=True, caption=f"Foto {i+1}")

                except Exception as e: st.error(f"Errore AI: {e}")
        else: st.warning("Carica un video.")

elif menu == "👑 Area Admin":
    st.title("👑 Pannello Admin Flotta")
    pw = st.text_input("Password", type="password")
    if pw == "GSSA2026":
        st.dataframe(df, use_container_width=True)
    elif pw: st.error("Password Errata")

if os.path.exists("temp_v.mp4"): os.remove("temp_v.mp4")

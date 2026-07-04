import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, re, pandas as pd
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF

# --- CONFIGURAZIONE API ---
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

@st.cache_resource
def ottieni_miglior_modello():
    try:
        modelli = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "gemini" in m.name]
        modelli.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)], reverse=True)
        return modelli[0] if modelli else "models/gemini-1.5-flash"
    except:
        return "models/gemini-1.5-flash"

MODELLO_ATTIVO = ottieni_miglior_modello()

TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE GOOGLE SHEETS ---
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
    step = max(1, total // 40) # 40 frame per non appesantire troppo la memoria
    for i in range(40):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        frame_res = cv2.resize(frame, (800, 600))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 75])
        frames.append({"image": cv2.cvtColor(frame_res, cv2.COLOR_BGR2RGB), "bytes": buffer.tobytes()})
    cap.release()
    return frames

def crea_pdf_report(targa, report_testo, esito_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA GSSA: {targa}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    if esito_nuovo: pdf.set_fill_color(255, 230, 230)
    else: pdf.set_fill_color(230, 255, 230)
    pdf.cell(0, 10, "DANNI RILEVATI" if esito_nuovo else "NESSUNA NUOVA ANOMALIA", ln=True, align="C", fill=True)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 10)
    testo_p = report_testo.replace("**", "").encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, testo_p)
    return pdf.output(dest='S')

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
df = carica_dati()

menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia Professionale")
    targa = st.selectbox("Seleziona Targa:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video", type=["mp4", "mov", "avi"])
    
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi IA in corso..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                frames = estrai_frame("temp.mp4")
                
                # Cerca storico
                row = df[df["Targa"] == targa].iloc[0]
                storico = str(row["Report"]) if pd.notna(row["Report"]) and row["Report"] != "" else "Nessuno"
                
                model = genai.GenerativeModel(MODELLO_ATTIVO)
                prompt = (f"Analisi per furgone {targa}. Storico: {storico}. "
                          "Confronta i fotogrammi con lo storico. "
                          "Se non vedi nuovi danni rispondi ESATTAMENTE: 'NESSUN NUOVO DANNO'. "
                          "Altrimenti elenca i nuovi danni per zona. Sii preciso.")
                
                immagini = [{"mime_type": "image/jpeg", "data": f['bytes']} for f in frames]
                
                try:
                    # Chiamata con sicurezza per evitare il blocco Response [200]
                    response = model.generate_content([prompt] + immagini)
                    
                    # LOGICA ESTRAZIONE TESTO ROBUSTA
                    try:
                        ris_ai = response.text.strip()
                    except:
                        if response.candidates:
                            ris_ai = response.candidates[0].content.parts[0].text.strip()
                        else:
                            ris_ai = "Errore: Risposta bloccata o non generata dall'IA."

                    nuovi = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    testo_final = ris_ai if nuovi or storico == "Nessuno" else "✅ Ispezione apposto, nessun nuovo danno rilevato rispetto al passato."
                    
                    # Aggiorna Database
                    if nuovi or storico == "Nessuno":
                        df.loc[df["Targa"] == targa, "Report"] = ris_ai
                    df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["Targa"] == targa, "Stato"] = "🚨 DANNI" if nuovi or storico == "Nessuno" else "✅ OK"
                    
                    # Carica su Google Sheets
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Analisi completata e salvata nel database!")
                    st.markdown(testo_final)
                    
                    # Generazione PDF
                    pdf_data = crea_pdf_report(targa, testo_final, nuovi or storico == "Nessuno")
                    st.download_button("📥 Scarica PDF Ufficiale", data=bytes(pdf_data), file_name=f"{targa}.pdf")
                    
                    # Galleria Mobile
                    st.divider()
                    cols = st.columns(2)
                    for i, f in enumerate(frames[:10]): # Mostra i primi 10 per controllo veloce
                        with cols[i%2]: st.image(f['image'], use_container_width=True)

                except Exception as e:
                    st.error(f"Errore tecnico durante la perizia: {str(e)}")
        else: st.warning("Manca il video.")

elif menu == "👑 Admin":
    st.title("Area Amministratore")
    pw = st.text_input("Password", type="password")
    if pw == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

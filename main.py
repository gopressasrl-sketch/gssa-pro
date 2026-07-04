import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, pandas as pd, base64, requests, json
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURAZIONE CHIAVI ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.getenv("GEMINI_API_KEY")

# Modello di punta 2026 (Gemini 2.0 Flash o superiore)
MODELLO_API = "gemini-2.0-flash" 

TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        return pd.DataFrame([{"Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for t in TARGHE_GSSA])

# --- FUNZIONE CHIAMATA DIRETTA GOOGLE (BYPASS LIBRERIA BUGGATA) ---
def chiama_gemini_diretto(prompt, frames_base64):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO_API}:generateContent?key={API_KEY}"
    
    # Preparazione dei dati per Google
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_base64]
    payload = {
        "contents": [{
            "parts": [{"text": prompt}] + inline_data
        }],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4000}
    }
    
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    
    if response.status_code == 200:
        res_json = response.json()
        try:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        except:
            return "NESSUN NUOVO DANNO"
    else:
        return f"Errore Server Google: {response.status_code} - {response.text}"

def estrai_frame_base64(video_path):
    frames_b64 = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 40) # 40 frame per restare nei limiti di peso della chiamata
    for i in range(40):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        frame_res = cv2.resize(frame, (640, 480)) # Dimensioni ottimizzate
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 70])
        frames_b64.append(base64.b64encode(buffer).decode('utf-8'))
    cap.release()
    return frames_b64

def crea_pdf_bytes(targa, report_testo, esito_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA GSSA - {targa}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(255, 230, 230) if esito_nuovo else pdf.set_fill_color(230, 255, 230)
    titolo = "VARIAZIONI RILEVATE" if esito_nuovo else "NESSUNA NUOVA ANOMALIA"
    pdf.cell(0, 10, titolo, ln=True, align="C", fill=True)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 7, report_testo.replace("**", "").encode('latin-1', 'replace').decode('latin-1'))
    return pdf.output(dest='S')

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO 2026", layout="wide")
df = carica_dati()

st.sidebar.title("💎 GSSA PRO v3.5")
menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Area Admin"])

if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia Diretta AI")
    targa = st.selectbox("Seleziona Targa:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video Ispezione", type=["mp4", "mov"])
    
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi in corso tramite connessione sicura HTTPS..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                
                # Estrazione frame e conversione per API
                immagini_b64 = estrai_frame_base64("temp.mp4")
                
                # Storico da Google Sheets
                row = df[df["Targa"] == targa].iloc[0]
                storico = str(row["Report"]) if pd.notna(row["Report"]) and row["Report"] != "" else "Nessuno"
                
                prompt = (f"Sei un perito esperto. Analizza i danni del furgone {targa}. "
                          f"Storico danni precedenti: {storico}. "
                          "Se non vedi NUOVI danni rispetto allo storico, rispondi 'NESSUN NUOVO DANNO'. "
                          "Altrimenti elenca i nuovi danni in modo dettagliato per zona.")
                
                # CHIAMATA DIRETTA
                ris_ai = chiama_gemini_diretto(prompt, immagini_b64)
                
                if "Errore Server" in ris_ai:
                    st.error(ris_ai)
                else:
                    is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    testo_final = ris_ai if is_nuovo or storico == "Nessuno" else "✅ Ispezione apposto, nessun nuovo danno rilevato."
                    
                    # Salvataggio
                    if is_nuovo or storico == "Nessuno":
                        df.loc[df["Targa"] == targa, "Report"] = ris_ai
                    df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["Targa"] == targa, "Stato"] = "🚨 DANNI" if is_nuovo else "✅ OK"
                    
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Sincronizzazione Cloud completata!")
                    st.markdown(testo_final)
                    
                    pdf_data = crea_pdf_bytes(targa, testo_final, is_nuovo)
                    st.download_button("📥 Scarica PDF", data=bytes(pdf_data), file_name=f"{targa}.pdf")
        else: st.warning("Carica un video.")

elif menu == "👑 Area Admin":
    st.title("Area Amministratore")
    pw = st.text_input("Password", type="password")
    if pw == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

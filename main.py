import streamlit as st
import os, cv2, json, re
from datetime import datetime
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv
from fpdf import FPDF

# --- CONFIGURAZIONE CHIAVE API (CLOUD + LOCALE) ---
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
else:
    load_dotenv()
    GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)
DB_FILE = "archivio_flotta.json"

@st.cache_resource
def ottieni_miglior_modello():
    try:
        modelli_validi = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods and "gemini" in m.name]
        modelli_validi.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)], reverse=True)
        return modelli_validi[0]
    except: return "models/gemini-1.5-flash"

MODELLO_ATTIVO = ottieni_miglior_modello()

TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

def carica_db():
    if not os.path.exists(DB_FILE):
        db = {t: {"stato": "DA CONTROLLARE", "data": "-", "report": ""} for t in TARGHE_GSSA}
        with open(DB_FILE, "w") as f: json.dump(db, f, indent=4)
    with open(DB_FILE, "r") as f: return json.load(f)

def salva_db(dati):
    with open(DB_FILE, "w") as f: json.dump(dati, f, indent=4)

def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    num_frames = 50 
    step = max(1, total // num_frames)
    for i in range(num_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        frame_res = cv2.resize(frame, (1024, 768))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 80])
        frames.append({"image": cv2.cvtColor(frame_res, cv2.COLOR_BGR2RGB), "bytes": buffer.tobytes()})
    cap.release()
    return frames

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

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
db = carica_db()

st.title("🚚 GSSA PRO - Gestione Ispezioni")
targa_selezionata = st.sidebar.selectbox("Seleziona Targa:", TARGHE_GSSA)
info = db[targa_selezionata]

tab1, tab2 = st.tabs(["🔍 NUOVA ANALISI", "📂 ARCHIVIO"])

with tab1:
    video_file = st.file_uploader("Carica Video", type=["mp4", "mov", "avi"])
    if st.button("🚀 AVVIA PERIZIA"):
        if video_file:
            with st.spinner("Analisi in corso..."):
                with open("temp_v.mp4", "wb") as f: f.write(video_file.read())
                frames = estrai_frame("temp_v.mp4")
                storico = info.get("report", "")
                is_prima = storico == "" or "NESSUN DANNO" in storico.upper()

                model = genai.GenerativeModel(MODELLO_ATTIVO)
                if is_prima:
                    prompt = f"PRIMA REGISTRAZIONE VEICOLO {targa_selezionata}. Elenca ogni danno visibile zonale nei 50 frame."
                else:
                    prompt = f"CONFRONTO VEICOLO {targa_selezionata}.\nSTORICO: {storico}\nSe non ci sono nuovi danni rispondi esattamente 'NESSUN NUOVO DANNO'."

                contenuto = [{"mime_type": "image/jpeg", "data": f['bytes']} for f in frames]
                try:
                    response = model.generate_content([prompt] + contenuto)
                    ris_ai = response.text.strip()
                    nuovi = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    
                    testo_final = ris_ai if nuovi or is_prima else "✅ Ispezione apposto, nessun nuovo danno rilevato."
                    if nuovi or is_prima: db[targa_selezionata]["report"] = ris_ai
                    db[targa_selezionata]["data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    db[targa_selezionata]["stato"] = "🚨 DANNI" if nuovi or is_prima else "✅ OK"
                    salva_db(db)
                    
                    st.markdown(testo_final)
                    pdf_data = crea_pdf_report(targa_selezionata, testo_final, nuovi or is_prima)
                    st.download_button("📥 SCARICA PDF", data=bytes(pdf_data) if isinstance(pdf_data, (bytes, bytearray)) else pdf_data.encode('latin-1'), file_name=f"Report_{targa_selezionata}.pdf")
                except Exception as e: st.error(f"Errore: {e}")
        else: st.warning("Manca il video.")

with tab2:
    if info["report"]:
        st.write(f"Data: {info['data']}")
        st.markdown(info["report"])

if os.path.exists("temp_v.mp4"): os.remove("temp_v.mp4")

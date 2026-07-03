import streamlit as st
import os, cv2, json, re
from datetime import datetime
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv
from fpdf import FPDF

# --- CONFIGURAZIONE ---
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

TARGHE_GSSA = [
    "HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", 
    "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", 
    "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", 
    "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", 
    "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", 
    "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", 
    "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", 
    "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", 
    "GG192ZN", "GG163HW", "GJ873LS"
]

# --- FUNZIONI DI SUPPORTO ---

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
        frame_res = cv2.resize(frame, (1280, 960))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frames.append({"image": cv2.cvtColor(frame_res, cv2.COLOR_BGR2RGB), "bytes": buffer.tobytes()})
    cap.release()
    return frames

def crea_pdf_report(targa, report_testo, esito_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA VEICOLO: {targa}", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    
    # Box Esito
    if esito_nuovo:
        pdf.set_fill_color(255, 230, 230) 
        testo_box = "ESITO: RILEVATI DANNI / VARIAZIONI"
    else:
        pdf.set_fill_color(230, 255, 230) 
        testo_box = "ESITO: NESSUNA NUOVA ANOMALIA - MEZZO CONFERMATO"
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, testo_box, ln=True, align="C", fill=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", "", 11)
    # Pulizia testo per evitare errori di codifica nel PDF
    testo_pulito = report_testo.replace("**", "").replace("#", "").encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, testo_pulito)
    
    # Restituisce i byte direttamente (correzione errore bytearray)
    out = pdf.output(dest='S')
    if isinstance(out, str):
        return out.encode('latin-1')
    return bytes(out)

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
db = carica_db()

st.title("🚚 GSSA PRO - Ispezione & Certificazione PDF")

targa_selezionata = st.sidebar.selectbox("Seleziona Veicolo:", TARGHE_GSSA)
info = db[targa_selezionata]

tab1, tab2 = st.tabs(["🔍 ANALISI VIDEO", "📂 ARCHIVIO STORICO"])

with tab1:
    video_file = st.file_uploader("Carica Video Ispezione", type=["mp4", "mov", "avi"])
    
    if st.button("🚀 AVVIA PERIZIA"):
        if video_file:
            with st.spinner("Confronto con lo storico in corso..."):
                with open("temp_v.mp4", "wb") as f: f.write(video_file.read())
                frames = estrai_frame("temp_v.mp4")
                
                # Storico precedente
                storico_precedente = info.get("report", "")
                prima_registrazione = storico_precedente == "" or "NESSUN DANNO" in storico_precedente.upper()

                model = genai.GenerativeModel(MODELLO_ATTIVO)
                
                if prima_registrazione:
                    prompt = (f"PRIMA REGISTRAZIONE VEICOLO {targa_selezionata}. "
                              "Analizza i 50 fotogrammi e fai un inventario di ogni danno visibile zonale.")
                else:
                    prompt = (f"CONFRONTO DANNI VEICOLO {targa_selezionata}.\n"
                              f"STORICO PRECEDENTE: {storico_precedente}\n\n"
                              "ISTRUZIONI:\n"
                              "1. Confronta i 50 nuovi fotogrammi con lo storico.\n"
                              "2. Se NON ci sono nuovi danni rispetto a quelli già scritti nello storico, "
                              "rispondi ESATTAMENTE: 'NESSUN NUOVO DANNO'.\n"
                              "3. Se vedi nuovi danni, elenca solo le novità.")

                contenuto = [{"mime_type": "image/jpeg", "data": f['bytes']} for f in frames]
                
                try:
                    response = model.generate_content([prompt] + contenuto)
                    risultato_ai = response.text.strip()
                    
                    nuovi_danni = "NESSUN NUOVO DANNO" not in risultato_ai.upper()
                    
                    if not nuovi_danni and not prima_registrazione:
                        testo_mostrato = "✅ Ispezione apposto, nessun nuovo danno rilevato rispetto al controllo precedente."
                        esito_pdf = False
                    else:
                        testo_mostrato = risultato_ai
                        esito_pdf = True

                    # Salvataggio DB
                    if nuovi_danni or prima_registrazione:
                        db[targa_selezionata]["report"] = risultato_ai
                    
                    db[targa_selezionata]["data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    db[targa_selezionata]["stato"] = "🚨 DANNI" if esito_pdf else "✅ OK"
                    salva_db(db)
                    
                    # Risultato UI
                    if esito_pdf: st.error(testo_mostrato)
                    else: st.success(testo_mostrato)
                    
                    # Tasto PDF
                    pdf_data = crea_pdf_report(targa_selezionata, testo_mostrato, esito_pdf)
                    st.download_button(
                        label="📥 SCARICA REPORT UFFICIALE (PDF)",
                        data=pdf_data,
                        file_name=f"Report_{targa_selezionata}.pdf",
                        mime="application/pdf"
                    )

                    st.divider()
                    st.subheader("Fotogrammi Analizzati")
                    cols = st.columns(4)
                    for i, f in enumerate(frames[:8]):
                        with cols[i%4]: st.image(f['image'], use_container_width=True)

                except Exception as e: st.error(f"Errore: {e}")
        else: st.warning("Manca il video.")

with tab2:
    if info["report"]:
        st.write(f"**Ultimo controllo:** {info['data']}")
        st.markdown(info["report"])
    else: st.write("Nessun dato.")

if os.path.exists("temp_v.mp4"): os.remove("temp_v.mp4")
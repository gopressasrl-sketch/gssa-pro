import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, pandas as pd, base64, requests, json, numpy as np
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF
import unicodedata

# --- CONFIGURAZIONE API ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=API_KEY)

@st.cache_resource
def seleziona_miglior_modello():
    try:
        modelli = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        priorita = ["3.5", "3.1", "3.0", "2.5", "2.0"]
        for p in priorita:
            for m in modelli:
                if p in m: return m
        return "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

MODELLO_ATTIVO = seleziona_miglior_modello()

# --- MAPPATURA VEICOLI ---
MAPPA_VIN_TARGA = {
    "VF7YAANFA12S97743": "GG730AV", "VF7YAANFA12T50337": "GG206JK",
    "VF7YAANFA12T90153": "GG243ZM", "VF7YAANFA12T70979": "GG677RR",
    "VF7YAANFA12T93188": "GG927ZP", "VF7YAANFA12T91627": "GG429ZP",
    "VF7YAANFA12T90957": "GG208ZN", "VF3YAANFA12T90411": "GG790ZL",
    "VF3YAANFA12T92295": "GG075ZP", "VF7YAANFA12T46333": "GG834JH",
    "VF7YAANFA12S86619": "GG736AV", "VF7YAANFA12T42666": "GG477JF",
    "W1VVUCFZ6T4541044": "HB183CY", "W1VVUCFZ0T4541010": "HB284CY",
    "W1VVUCFZ0T4536437": "HB339CY", "W1VVUCFZ4T4543617": "HB184CY",
    "VF3YABPF612Y68182": "GS595DF", "VF3YABPF912Y68581": "GS597DF",
    "ZFA250003SMB27292": "GZ399JY", "ZFA25000XSMB26849": "GZ401JY",
    "VXFVLEHT5SU312069": "HA412FV", "VFEVLEHT8SZ058970": "HA717DG",
    "VF3VLEHT2SZ058981": "HA630DC", "VXFVLEHT1SU319536": "HA881MM",
    "VXFVLEHT1SZ044821": "GZ249ZS", "VF3VLEHT6S7817160": "GZ023SB",
    "VXFVLEHT5SU308023": "HA668DG", "VF3VLEHT3SU320388": "HA942FV",
    "VF3VLEHT2SU318132": "HA953FV", "VF3VLEHT0SU318131": "HA957FV",
    "ZFA250005SMB27620": "GZ532JY"
}
LISTA_VIN = list(MAPPA_VIN_TARGA.keys())

# --- CONNESSIONE DATABASE ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        df_read = conn.read(worksheet="ispezioni", ttl="0s")
        return df_read.fillna("").astype(str).replace(['None', 'nan', 'NaN'], '')
    except:
        data = [{"VIN": v, "Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": "", "Operatore": ""} for v, t in MAPPA_VIN_TARGA.items()]
        return pd.DataFrame(data).astype(str)

def salva_dati(df_to_save):
    df_to_save = df_to_save.fillna("").astype(str).replace(['None', 'nan', 'NaN'], '')
    conn.update(worksheet="ispezioni", data=df_to_save)
    return True

# --- FUNZIONI PDF ---
def pulizia_per_pdf(testo):
    if not testo or testo == "nan": return "Nessun dettaglio."
    testo = testo.replace("ë", "e").replace("Ë", "E").replace("’", "'").replace("•", "-")
    nfkd_form = unicodedata.normalize('NFKD', testo)
    testo_no_accenti = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    testo_finale = testo_no_accenti.encode('ascii', 'ignore').decode('ascii')
    return testo_finale.replace("**", "").replace("#", "").strip()

def crea_pdf_bytes(targa, vin, testo, stato, data_report, operatore):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA VEICOLO: {pulizia_per_pdf(targa)}", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 7, f"VIN: {pulizia_per_pdf(vin)} | Operatore: {pulizia_per_pdf(operatore)}", ln=True, align="C")
    pdf.cell(0, 7, f"Data Ispezione: {data_report}", ln=True, align="C")
    pdf.ln(10)
    if "OK" in stato.upper(): pdf.set_fill_color(200, 255, 200)
    else: pdf.set_fill_color(255, 200, 200)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"STATO: {pulizia_per_pdf(stato)}", ln=True, align="C", fill=True)
    pdf.ln(5); pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 7, pulizia_per_pdf(testo))
    return bytes(pdf.output(dest='S'))

# --- FUNZIONI AI E VIDEO (OTTIMIZZATE) ---
def chiama_gemini(prompt, frames_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODELLO_ATTIVO}:generateContent?key={API_KEY}"
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_b64]
    payload = {"contents": [{"parts": [{"text": prompt}] + inline_data}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4000}}
    # Aumentato timeout a 300 secondi per evitare ReadTimeout
    res = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=300)
    if res.status_code == 200:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    return f"Errore AI ({res.status_code})"

def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # Ridotto a 30 fotogrammi per velocità e stabilità
    num_frames = 30
    step = max(1, total // num_frames)
    for i in range(num_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step); ret, frame = cap.read()
        if not ret: break
        # Compressione al 50% per alleggerire il pacchetto dati
        _, buff = cv2.imencode('.jpg', cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 50])
        frames.append(base64.b64encode(buff).decode('utf-8'))
    cap.release()
    return frames

# --- UI APP ---
st.set_page_config(page_title="GSSA PRO", layout="wide")

if 'user' not in st.session_state:
    st.title("🚚 Accesso Operatore")
    nome = st.text_input("Nome")
    cognome = st.text_input("Cognome")
    if st.button("ACCEDI ALLA FLOTTA"):
        if nome and cognome:
            st.session_state.user = f"{nome.strip()} {cognome.strip()}".upper()
            st.rerun()
    st.stop()

df = carica_dati()
if 'vin_attuale' not in st.session_state: st.session_state.vin_attuale = LISTA_VIN[0]
if 'mostra_camera' not in st.session_state: st.session_state.mostra_camera = False

st.sidebar.title("Furgoni GSSA")
st.sidebar.success(f"👤 {st.session_state.user}")
menu = st.sidebar.radio("Vai a:", ["🔍 Ispezione", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione":
    st.title("Nuova Ispezione")
    if not st.session_state.mostra_camera:
        if st.button("📷 SCANSIONA VIN", use_container_width=True):
            st.session_state.mostra_camera = True; st.rerun()
    else:
        if st.button("❌ CHIUDI"): st.session_state.mostra_camera = False; st.rerun()
        qr_img = st.camera_input("Inquadra il QR Code")
        if qr_img:
            file_bytes = np.asarray(bytearray(qr_img.read()), dtype=np.uint8)
            detector = cv2.QRCodeDetector()
            vin_rilevato, _, _ = detector.detectAndDecode(cv2.imdecode(file_bytes, 1))
            if vin_rilevato and vin_rilevato.upper().strip() in LISTA_VIN:
                st.session_state.vin_attuale = vin_rilevato.upper().strip()
                st.session_state.mostra_camera = False; st.rerun()

    vin_corrente = st.selectbox("Veicolo:", LISTA_VIN, index=LISTA_VIN.index(st.session_state.vin_attuale))
    targa_corrente = MAPPA_VIN_TARGA[vin_corrente]
    st.info(f"Ispezione per: **{targa_corrente}**")

    video = st.file_uploader("Carica Video Giro Mezzo", type=["mp4", "mov"])
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi IA in corso (attendere circa 1 minuto)..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                b64_imgs = estrai_frame("temp.mp4")
                idx = df.index[df['VIN'] == vin_corrente].tolist()[0]
                storico = str(df.at[idx, "Report"])
                
                prompt = f"Analisi danni furgone {targa_corrente}. Storico: {storico}. Elenca NUOVI danni o rispondi 'NESSUN NUOVO DANNO'. Nota se la targa e' diversa."
                ris_ai = chiama_gemini(prompt, b64_imgs)
                
                if "Errore" not in ris_ai:
                    is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    data_ora = datetime.now().strftime("%d/%m/%Y %H:%M")
                    stato_f = "DANNI RILEVATI" if is_nuovo else "OK"
                    df.at[idx, "Report"] = str(ris_ai)
                    df.at[idx, "Data"] = data_ora
                    df.at[idx, "Stato"] = stato_f
                    df.at[idx, "Operatore"] = st.session_state.user
                    
                    if salva_dati(df):
                        st.success("Analisi completata!")
                        st.markdown(ris_ai)
                        pdf_b = crea_pdf_bytes(targa_corrente, vin_corrente, ris_ai, stato_f, data_ora, st.session_state.user)
                        st.download_button("📥 SCARICA PDF", data=pdf_b, file_name=f"Report_{targa_corrente}.pdf", mime="application/pdf")
                else:
                    st.error(ris_ai)
        else: st.warning("Carica il video!")

elif menu == "📂 Archivio":
    st.title("📂 Archivio")
    vin_cerca = st.selectbox("Seleziona Veicolo:", LISTA_VIN)
    idx_list = df.index[df['VIN'] == vin_cerca].tolist()
    if idx_list:
        r = df.iloc[idx_list[0]]
        st.subheader(f"Mezzo: {r['Targa']}")
        st.write(f"Stato: {r['Stato']} | Operatore: {r['Operatore']} | Data: {r['Data']}")
        if r['Report'] and str(r['Report']).strip() != "":
            st.markdown("---")
            st.markdown(r['Report'])
            pdf_b = crea_pdf_bytes(r['Targa'], r['VIN'], r['Report'], r['Stato'], r['Data'], r['Operatore'])
            st.download_button(label=f"📥 SCARICA PDF", data=pdf_b, file_name=f"Report_{r['Targa']}.pdf", mime="application/pdf")

elif menu == "👑 Admin":
    st.title("👑 Admin")
    if st.text_input("Password", type="password") == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

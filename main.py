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

# --- MAPPATURA ---
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

# --- CONNESSIONE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        df_read = conn.read(worksheet="ispezioni", ttl="0s")
        return df_read.astype(str).replace(['None', 'nan', 'NaN'], '')
    except:
        data = [{"VIN": v, "Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for v, t in MAPPA_VIN_TARGA.items()]
        return pd.DataFrame(data).astype(str)

def salva_dati(df_to_save):
    df_to_save = df_to_save.astype(str).replace(['None', 'nan', 'NaN'], '')
    conn.update(worksheet="ispezioni", data=df_to_save)
    return True

# --- FUNZIONI PDF E AI ---
def pulisci_testo_pdf(testo):
    """Rimuove EMOJI e caratteri non supportati per evitare il crash latin-1"""
    if not testo: return ""
    # Sostituzioni manuali per Citroën e simboli comuni
    testo = testo.replace("ë", "e").replace("Ë", "E").replace("’", "'").replace("•", "-")
    # Rimuove EMOJI e caratteri non-latin1 (come la sirena 🚨)
    testo_pulito = "".join(c for c in testo if ord(c) < 256)
    # Normalizzazione finale
    return testo_pulito.replace("**", "").replace("#", "").strip()

def crea_pdf_bytes(targa, vin, testo, stato, data_report):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA VEICOLO: {targa}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Telaio (VIN): {vin}", ln=True, align="C")
    pdf.cell(0, 8, f"Data Ispezione: {data_report}", ln=True, align="C")
    pdf.ln(10)
    
    if "OK" in stato: pdf.set_fill_color(200, 255, 200)
    else: pdf.set_fill_color(255, 200, 200)
    
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, f"STATO: {stato}", ln=True, align="C", fill=True)
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "", 10)
    testo_sicuro = pulisci_testo_pdf(testo)
    pdf.multi_cell(0, 7, testo_sicuro)
    
    out = pdf.output(dest='S')
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode('latin-1')

def chiama_gemini(prompt, frames_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODELLO_ATTIVO}:generateContent?key={API_KEY}"
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_b64]
    payload = {"contents": [{"parts": [{"text": prompt}] + inline_data}], "generationConfig": {"temperature": 0.1}}
    res = requests.post(url, json=payload, timeout=120)
    if res.status_code == 200:
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    return "Errore AI"

def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 40)
    for i in range(40):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step); ret, frame = cap.read()
        if not ret: break
        _, buff = cv2.imencode('.jpg', cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 60])
        frames.append(base64.b64encode(buff).decode('utf-8'))
    cap.release()
    return frames

# --- UI APP ---
st.set_page_config(page_title="GSSA PRO", layout="wide")
df = carica_dati()

if 'vin_attuale' not in st.session_state: st.session_state.vin_attuale = LISTA_VIN[0]
if 'mostra_camera' not in st.session_state: st.session_state.mostra_camera = False

st.sidebar.title("Furgoni GSSA")
menu = st.sidebar.radio("Naviga:", ["🔍 Ispezione", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione":
    st.title("Nuova Ispezione")
    if not st.session_state.mostra_camera:
        if st.button("📷 SCANSIONA VIN", use_container_width=True):
            st.session_state.mostra_camera = True
            st.rerun()
    else:
        if st.button("❌ CHIUDI CAMERA"): st.session_state.mostra_camera = False; st.rerun()
        qr_img = st.camera_input("Inquadra il VIN")
        if qr_img:
            file_bytes = np.asarray(bytearray(qr_img.read()), dtype=np.uint8)
            detector = cv2.QRCodeDetector()
            vin_rilevato, _, _ = detector.detectAndDecode(cv2.imdecode(file_bytes, 1))
            if vin_rilevato.upper().strip() in LISTA_VIN:
                st.session_state.vin_attuale = vin_rilevato.upper().strip()
                st.session_state.mostra_camera = False; st.rerun()

    vin_corrente = st.selectbox("Veicolo:", LISTA_VIN, index=LISTA_VIN.index(st.session_state.vin_attuale))
    targa_corrente = MAPPA_VIN_TARGA[vin_corrente]
    st.warning(f"🚗 In Ispezione: {targa_corrente}")

    video = st.file_uploader("Carica Video", type=["mp4", "mov"])
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi in corso..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                b64_imgs = estrai_frame("temp.mp4")
                
                idx = df.index[df['VIN'] == vin_corrente].tolist()[0]
                storico = str(df.at[idx, "Report"])
                
                prompt = f"Analisi danni furgone {targa_corrente}. Storico: {storico}. Elenca NUOVI danni o rispondi 'NESSUN NUOVO DANNO'. Nota se la targa nel video è diversa da {targa_corrente}."
                ris_ai = chiama_gemini(prompt, b64_imgs)
                
                is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                data_ora = datetime.now().strftime("%d/%m/%Y %H:%M")
                stato_f = "🚨 DANNI" if is_nuovo else "✅ OK"
                
                df.at[idx, "Report"] = str(ris_ai)
                df.at[idx, "Data"] = data_ora
                df.at[idx, "Stato"] = stato_f
                
                if salva_dati(df):
                    st.success("Analisi completata!")
                    st.markdown(ris_ai)
                    try:
                        pdf_b = crea_pdf_bytes(targa_corrente, vin_corrente, ris_ai, stato_f, data_ora)
                        st.download_button("📥 SCARICA REPORT PDF", data=pdf_b, file_name=f"Report_{targa_corrente}.pdf", mime="application/pdf")
                    except Exception as e:
                        st.error(f"Errore PDF risolto: ricarica la pagina.")
        else: st.warning("Metti il video!")

elif menu == "📂 Archivio":
    st.title("📂 Archivio Storico")
    vin_cerca = st.selectbox("Seleziona Veicolo:", LISTA_VIN)
    idx_list = df.index[df['VIN'] == vin_cerca].tolist()
    if idx_list:
        r = df.iloc[idx_list[0]]
        st.subheader(f"Mezzo: {r['Targa']}")
        st.write(f"**Stato:** {r['Stato']} | **Data:** {r['Data']}")
        if r['Report'] and str(r['Report']) != "":
            st.markdown("---")
            st.markdown(r['Report'])
            try:
                pdf_b = crea_pdf_bytes(r['Targa'], r['VIN'], r['Report'], r['Stato'], r['Data'])
                st.download_button(label=f"📥 SCARICA PDF", data=pdf_b, file_name=f"Report_{r['Targa']}.pdf", mime="application/pdf")
            except: st.error("Errore generazione PDF nell'archivio.")

elif menu == "👑 Admin":
    st.title("Admin")
    if st.text_input("Password", type="password") == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

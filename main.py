import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, pandas as pd, base64, requests, json, numpy as np
from datetime import datetime
import google.generativeai as genai

# --- CONFIGURAZIONE API ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=API_KEY)

# --- AUTO-SELEZIONE MODELLO 2026 ---
@st.cache_resource
def seleziona_miglior_modello():
    try:
        modelli = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        priorita = ["3.5", "3.1", "3.0", "2.5", "2.0"]
        for p in priorita:
            for m in modelli:
                if p in m: return m
        return "models/gemini-2.0-flash"
    except: return "models/gemini-2.0-flash"

MODELLO_ATTIVO = seleziona_miglior_modello()

# --- MAPPATURA VIN <-> TARGA ---
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

# --- DATABASE ---
conn = st.connection("gsheets", type=GSheetsConnection)
def carica_dati():
    try: return conn.read(worksheet="ispezioni", ttl="0s")
    except: return pd.DataFrame([{"VIN": v, "Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for v, t in MAPPA_VIN_TARGA.items()])

def chiama_gemini_ispezione(prompt, frames_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/{MODELLO_ATTIVO}:generateContent?key={API_KEY}"
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_b64]
    payload = {"contents": [{"parts": [{"text": prompt}] + inline_data}], "generationConfig": {"temperature": 0.1}}
    res = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload), timeout=120)
    return res.json()['candidates'][0]['content']['parts'][0]['text'] if res.status_code == 200 else "Errore AI"

def estrai_frame_base64(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 40)
    for i in range(40):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step); ret, frame = cap.read()
        if not ret: break
        _, buff = cv2.imencode('.jpg', cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 65])
        frames.append(base64.b64encode(buff).decode('utf-8'))
    cap.release()
    return frames

# --- UI APP ---
st.set_page_config(page_title="GSSA PRO QR", layout="wide")
df = carica_dati()

# Inizializzazione degli stati della sessione
if 'vin_attuale' not in st.session_state: st.session_state.vin_attuale = LISTA_VIN[0]
if 'mostra_camera' not in st.session_state: st.session_state.mostra_camera = False

st.sidebar.title("💎 GSSA PRO v5.1")
st.sidebar.info(f"AI: {MODELLO_ATTIVO.split('/')[-1]}")
menu = st.sidebar.radio("Menu", ["🔍 Ispezione", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione":
    st.title("🚀 Avvia Ispezione Mezzo")

    # BOTTONE PER APRIRE LA CAMERA
    if not st.session_state.mostra_camera:
        if st.button("📷 SCANSIONA VIN (QR CODE)", use_container_width=True):
            st.session_state.mostra_camera = True
            st.rerun()
    else:
        if st.button("❌ CHIUDI FOTOCAMERA", use_container_width=True):
            st.session_state.mostra_camera = False
            st.rerun()
        
        # CAMERA INPUT (Appare solo se mostrata_camera è True)
        qr_img = st.camera_input("Inquadra il codice VIN sul furgone")
        if qr_img:
            file_bytes = np.asarray(bytearray(qr_img.read()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)
            detector = cv2.QRCodeDetector()
            vin_rilevato, _, _ = detector.detectAndDecode(img)
            
            if vin_rilevato.upper().strip() in LISTA_VIN:
                st.session_state.vin_attuale = vin_rilevato.upper().strip()
                st.session_state.mostra_camera = False # Chiude la camera automaticamente
                st.success(f"✅ VEICOLO RICONOSCIUTO: {MAPPA_VIN_TARGA[st.session_state.vin_attuale]}")
                st.rerun()
            else:
                st.error("❌ QR non valido. Riprova o seleziona manualmente.")

    # SELEZIONE E VIDEO
    st.divider()
    vin_corrente = st.selectbox("Veicolo selezionato:", LISTA_VIN, index=LISTA_VIN.index(st.session_state.vin_attuale))
    st.warning(f"🚗 Ispezione per: **{MAPPA_VIN_TARGA[vin_corrente]}**")

    video = st.file_uploader("📷 Carica Video Giro Mezzo", type=["mp4", "mov"])
    if st.button("🚀 AVVIA ANALISI TOTALE"):
        if video:
            with st.spinner("Analisi in corso..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                b64_imgs = estrai_frame_base64("temp.mp4")
                riga = df[df["VIN"] == vin_corrente]
                storico = str(riga.iloc[0]["Report"]) if not riga.empty and pd.notna(riga.iloc[0]["Report"]) else "Nessuno"
                prompt = f"Analisi danni {MAPPA_VIN_TARGA[vin_corrente]}. Storico: {storico}. Elenca solo NUOVI danni o rispondi 'NESSUN NUOVO DANNO'."
                ris_ai = chiama_gemini_ispezione(prompt, b64_imgs)
                st.markdown(ris_ai)
                if "Errore" not in ris_ai:
                    is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                    df.loc[df["VIN"] == vin_corrente, "Report"] = ris_ai if is_nuovo or storico == "Nessuno" else storico
                    df.loc[df["VIN"] == vin_corrente, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                    df.loc[df["VIN"] == vin_corrente, "Stato"] = "🚨 DANNI" if is_nuovo else "✅ OK"
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Sincronizzato!")
        else: st.warning("Carica il video!")

elif menu == "👑 Admin":
    st.title("👑 Admin Panel")
    if st.text_input("Password", type="password") == "GSSA2026":
        st.dataframe(df, use_container_width=True)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

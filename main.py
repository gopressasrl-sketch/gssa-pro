import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, pandas as pd, base64, requests, json, numpy as np
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURAZIONE API ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.getenv("GEMINI_API_KEY")

MODELLO_API = "gemini-2.0-flash" 

# --- MAPPATURA UFFICIALE VIN <-> TARGA ---
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
LISTA_TARGHE = list(MAPPA_VIN_TARGA.values())

# --- CONNESSIONE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        data = [{"VIN": v, "Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for v, t in MAPPA_VIN_TARGA.items()]
        df_ini = pd.DataFrame(data)
        conn.update(worksheet="ispezioni", data=df_ini)
        return df_ini

# --- FUNZIONI DI SCANSIONE ---
def leggi_qr(image_file):
    file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, 1)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    return data.upper().strip()

def leggi_targa_ia(image_file):
    """Usa Gemini per leggere la targa dalla foto"""
    img_bytes = base64.b64encode(image_file.read()).decode('utf-8')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO_API}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [
            {"text": "Leggi la targa automobilistica italiana in questa foto. Rispondi solo con la targa senza spazi."},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_bytes}}
        ]}]
    }
    res = requests.post(url, json=payload)
    if res.status_code == 200:
        return res.json()['candidates'][0]['content']['parts'][0]['text'].strip().upper()
    return ""

def chiama_gemini_ispezione(prompt, frames_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO_API}:generateContent?key={API_KEY}"
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_b64]
    payload = {"contents": [{"parts": [{"text": prompt}] + inline_data}], "generationConfig": {"temperature": 0.1}}
    res = requests.post(url, json=payload)
    return res.json()['candidates'][0]['content']['parts'][0]['text'] if res.status_code == 200 else "Errore AI"

def estrai_frame_base64(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 40)
    for i in range(40):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step); ret, frame = cap.read()
        if not ret: break
        _, buff = cv2.imencode('.jpg', cv2.resize(frame, (640, 480)), [cv2.IMWRITE_JPEG_QUALITY, 70])
        frames.append(base64.b64encode(buff).decode('utf-8'))
    cap.release()
    return frames

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA SMART SCAN", layout="wide")
df = carica_dati()

if 'vin_attuale' not in st.session_state: st.session_state.vin_attuale = LISTA_VIN[0]

st.sidebar.title("💎 GSSA PRO v4.5")
menu = st.sidebar.radio("Menu", ["🔍 Ispezione Rapida", "📂 Archivio", "👑 Admin"])

if menu == "🔍 Ispezione Rapida":
    st.title("🚀 Identifica Veicolo")
    
    metodo = st.radio("Scegli come identificare il mezzo:", ["Scansiona QR (VIN)", "Scansiona Targa (OCR)", "Selezione Manuale"])
    
    if metodo == "Scansiona QR (VIN)":
        foto_qr = st.camera_input("Inquadra il QR Code sul telaio")
        if foto_qr:
            vin_letto = leggi_qr(foto_qr)
            if vin_letto in LISTA_VIN:
                st.session_state.vin_attuale = vin_letto
                st.success(f"✅ Riconosciuto VIN: {vin_letto} ({MAPPA_VIN_TARGA[vin_letto]})")
            else: st.error("QR non valido o non in flotta.")

    elif metodo == "Scansiona Targa (OCR)":
        foto_targa = st.camera_input("Inquadra la targa del furgone")
        if foto_targa:
            with st.spinner("L'IA sta leggendo la targa..."):
                targa_letta = leggi_targa_ia(foto_targa)
                # Pulizia targa letta (rimuove spazi o caratteri strani)
                targa_letta = "".join(filter(str.isalnum, targa_letta))
                if targa_letta in LISTA_TARGHE:
                    # Trova il VIN corrispondente alla targa
                    vin_trovato = [v for v, t in MAPPA_VIN_TARGA.items() if t == targa_letta][0]
                    st.session_state.vin_attuale = vin_trovato
                    st.success(f"✅ Targa riconosciuta: {targa_letta}")
                else: st.error(f"Targa {targa_letta} non trovata in flotta.")

    # Riepilogo selezione
    vin_corrente = st.selectbox("Veicolo selezionato:", LISTA_VIN, index=LISTA_VIN.index(st.session_state.vin_attuale))
    targa_corrente = MAPPA_VIN_TARGA[vin_corrente]
    st.info(f"🚗 **Ispezione pronta per:** {targa_corrente} | **Telaio:** {vin_corrente}")

    # Analisi Video
    video = st.file_uploader("📷 Registra o carica il video del giro mezzo", type=["mp4", "mov"])
    if st.button("🚀 AVVIA PERIZIA"):
        if video:
            with st.spinner("Analisi peritale in corso..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                b64_imgs = estrai_frame_base64("temp.mp4")
                storico = str(df[df["VIN"] == vin_corrente].iloc[0]["Report"])
                
                prompt = f"Perizia {targa_corrente}. Storico: {storico}. Elenca nuovi danni o rispondi 'NESSUN NUOVO DANNO'."
                ris_ai = chiama_gemini_ispezione(prompt, b64_imgs)
                
                # Aggiornamento DB
                is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                df.loc[df["VIN"] == vin_corrente, "Report"] = ris_ai if is_nuovo else storico
                df.loc[df["VIN"] == vin_corrente, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                df.loc[df["VIN"] == vin_corrente, "Stato"] = "🚨 DANNI" if is_nuovo else "✅ OK"
                conn.update(worksheet="ispezioni", data=df)
                
                st.subheader("Risultato:")
                st.markdown(ris_ai)
        else: st.warning("Carica il video!")

elif menu == "👑 Admin":
    st.title("👑 Admin")
    if st.text_input("Password", type="password") == "GSSA2026":
        st.dataframe(df)

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

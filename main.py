import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, pandas as pd, base64, requests, json, numpy as np
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURAZIONE API GEMINI ---
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
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("Errore di configurazione Google Sheets nei Secrets.")

def carica_dati():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except Exception:
        # Se il foglio non è accessibile, creiamo un database temporaneo per non bloccare l'app
        data = [{"VIN": v, "Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for v, t in MAPPA_VIN_TARGA.items()]
        return pd.DataFrame(data)

# --- FUNZIONI DI SCANSIONE (QR E OCR) ---
def leggi_qr(image_file):
    file_bytes = np.asarray(bytearray(image_file.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, 1)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)
    return data.upper().strip()

def leggi_targa_ia(image_file):
    img_bytes = base64.b64encode(image_file.read()).decode('utf-8')
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO_API}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [
            {"text": "Leggi la targa automobilistica italiana in questa foto. Rispondi solo con la targa senza spazi."},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_bytes}}
        ]}]
    }
    try:
        res = requests.post(url, json=payload)
        return res.json()['candidates'][0]['content']['parts'][0]['text'].strip().upper()
    except: return ""

# --- ANALISI PERITALE VIDEO ---
def chiama_gemini_ispezione(prompt, frames_b64):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELLO_API}:generateContent?key={API_KEY}"
    inline_data = [{"inline_data": {"mime_type": "image/jpeg", "data": f}} for f in frames_b64]
    payload = {
        "contents": [{"parts": [{"text": prompt}] + inline_data}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4000}
    }
    try:
        res = requests.post(url, json=payload, timeout=60)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except: return "Errore di comunicazione con l'IA."

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

# --- INTERFACCIA APP ---
st.set_page_config(page_title="GSSA SMART SCAN", layout="wide", page_icon="🚚")
df = carica_dati()

# Gestione della selezione veicolo tra i vari refresh della pagina
if 'vin_attuale' not in st.session_state: 
    st.session_state.vin_attuale = LISTA_VIN[0]

st.sidebar.title("💎 GSSA PRO v4.5")
menu = st.sidebar.radio("Navigazione", ["🔍 Nuova Ispezione", "📂 Archivio Flotta", "👑 Area Admin"])

if menu == "🔍 Nuova Ispezione":
    st.title("🚀 Identifica Veicolo")
    
    scelta_metodo = st.radio("Metodo di identificazione:", ["QR Code (VIN)", "Scansione Targa (AI)", "Selezione Manuale"], horizontal=True)
    
    if scelta_metodo == "QR Code (VIN)":
        foto_qr = st.camera_input("Inquadra il QR Code sul telaio")
        if foto_qr:
            vin_letto = leggi_qr(foto_qr)
            if vin_letto in LISTA_VIN:
                st.session_state.vin_attuale = vin_letto
                st.success(f"✅ Riconosciuto VIN: {vin_letto} ({MAPPA_VIN_TARGA[vin_letto]})")
            else: st.error("QR non valido o veicolo non in flotta.")

    elif scelta_metodo == "Scansione Targa (AI)":
        foto_targa = st.camera_input("Scatta una foto alla targa")
        if foto_targa:
            with st.spinner("Riconoscimento targa in corso..."):
                t_letta = "".join(filter(str.isalnum, leggi_targa_ia(foto_targa)))
                if t_letta in LISTA_TARGHE:
                    v_trovato = [v for v, t in MAPPA_VIN_TARGA.items() if t == t_letta][0]
                    st.session_state.vin_attuale = v_trovato
                    st.success(f"✅ Targa riconosciuta: {t_letta}")
                else: st.error(f"Targa {t_letta} non trovata nel database.")

    # Selettore finale (si aggiorna con le scansioni sopra)
    vin_corrente = st.selectbox("Veicolo sotto ispezione:", LISTA_VIN, 
                                index=LISTA_VIN.index(st.session_state.vin_attuale))
    targa_corrente = MAPPA_VIN_TARGA[vin_corrente]
    
    st.warning(f"Ispezione attiva per: **{targa_corrente}** (VIN: {vin_corrente})")

    video = st.file_uploader("📷 Registra Video Giro Mezzo", type=["mp4", "mov"])
    
    if st.button("🚀 AVVIA ANALISI PERITALE"):
        if video:
            with st.spinner("L'intelligenza artificiale sta analizzando il video..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                b64_imgs = estrai_frame_base64("temp.mp4")
                
                # Cerca lo storico
                riga = df[df["VIN"] == vin_corrente]
                storico = str(riga.iloc[0]["Report"]) if not riga.empty and pd.notna(riga.iloc[0]["Report"]) else "Nessuno"
                
                prompt = f"Perizia professionale veicolo {targa_corrente}. Storico: {storico}. Elenca nuovi danni o scrivi 'NESSUN NUOVO DANNO'."
                ris_ai = chiama_gemini_ispezione(prompt, b64_imgs)
                
                is_nuovo = "NESSUN NUOVO DANNO" not in ris_ai.upper()
                
                # Aggiornamento Database
                df.loc[df["VIN"] == vin_corrente, "Report"] = ris_ai if is_nuovo or storico == "Nessuno" else storico
                df.loc[df["VIN"] == vin_corrente, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                df.loc[df["VIN"] == vin_corrente, "Stato"] = "🚨 DANNI" if is_nuovo else "✅ OK"
                
                try:
                    conn.update(worksheet="ispezioni", data=df)
                    st.success("Analisi salvata su Google Sheets!")
                except:
                    st.error("Errore nel salvataggio su Cloud. Controlla i permessi del foglio.")
                
                st.subheader("Esito AI:")
                st.markdown(ris_ai)
        else:
            st.warning("Carica un video per iniziare.")

elif menu == "📂 Archivio Flotta":
    st.title("📂 Storico Veicoli")
    vin_cerca = st.selectbox("Seleziona Veicolo:", LISTA_VIN)
    r = df[df["VIN"] == vin_cerca].iloc[0]
    st.subheader(f"Mezzo: {MAPPA_VIN_TARGA[vin_cerca]}")
    st.write(f"Stato: {r['Stato']} | Data: {r['Data']}")
    st.info(r["Report"] if r["Report"] else "Nessun report presente.")

elif menu == "👑 Admin":
    st.title("👑 Pannello Amministratore")
    if st.text_input("Password", type="password") == "GSSA2026":
        st.dataframe(df, use_container_width=True)
        st.download_button("📊 Scarica Database CSV", df.to_csv(index=False), "flotta.csv")

if os.path.exists("temp.mp4"): os.remove("temp.mp4")

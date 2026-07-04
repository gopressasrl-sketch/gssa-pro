import streamlit as st
from streamlit_gsheets import GSheetsConnection
import os, cv2, re, pandas as pd
from datetime import datetime
import google.generativeai as genai
from fpdf import FPDF

# --- CONFIGURAZIONE CHIAVE API ---
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_KEY)

# --- LISTA TARGHE UFFICIALE ---
TARGHE_GSSA = ["HB183CY", "HB284CY", "HB339CY", "HB184CY", "GG730AV", "GG243ZM", "GG677RR", "GG927ZP", "GG429ZP", "GG790ZL", "GG075ZP", "GG206JK", "GG834JH", "GG736AV", "GG477JF", "GZ399JY", "GZ401JY", "HA717DG", "GS597DF", "GZ532JY", "HA412FV", "HA630DC", "HA881MM", "GZ249ZS", "GZ023SB", "HA668DG", "HA942FV", "HA953FV", "HA957FV", "HA539SS", "GG392AW", "GG733AV", "GG303AW", "GG161HW", "GG850JH", "GG828JH", "GG831AV", "GG318AW", "GG484JF", "GG408AW", "GG341AW", "GG207JK", "GG558JH", "GG564JH", "GG181HW", "GG473JF", "GG208JK", "GG829JH", "GG192ZN", "GG163HW", "GJ873LS"]

# --- CONNESSIONE GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def carica_dati_gsheets():
    try:
        return conn.read(worksheet="ispezioni", ttl="0s")
    except:
        # Se il foglio è vuoto, creiamo la struttura iniziale
        df_iniziale = pd.DataFrame([{"Targa": t, "Stato": "DA CONTROLLARE", "Data": "-", "Report": ""} for t in TARGHE_GSSA])
        conn.update(worksheet="ispezioni", data=df_iniziale)
        return df_iniziale

# --- FUNZIONI VIDEO E PDF ---
def estrai_frame(video_path):
    frames = []
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // 50)
    for i in range(50):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ret, frame = cap.read()
        if not ret: break
        frame_res = cv2.resize(frame, (800, 600))
        _, buffer = cv2.imencode('.jpg', frame_res, [cv2.IMWRITE_JPEG_QUALITY, 70])
        frames.append({"image": cv2.cvtColor(frame_res, cv2.COLOR_BGR2RGB), "bytes": buffer.tobytes()})
    cap.release()
    return frames

def crea_pdf_bytes(targa, report_testo, esito_nuovo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"REPORT PERIZIA GSSA: {targa}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 10, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    colore = (255, 230, 230) if esito_nuovo else (230, 255, 230)
    pdf.set_fill_color(*colore)
    pdf.cell(0, 10, "RILEVATI NUOVI DANNI" if esito_nuovo else "NESSUNA NUOVA ANOMALIA", ln=True, align="C", fill=True)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    testo_p = report_testo.replace("**", "").encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, testo_p)
    return pdf.output(dest='S').encode('latin-1')

# --- INTERFACCIA ---
st.set_page_config(page_title="GSSA PRO CLOUD", layout="wide")
df = carica_dati_gsheets()

menu = st.sidebar.radio("Navigazione", ["🔍 Ispezione", "📂 Archivio", "👑 Area Admin"])

# --- 1. ISPEZIONE ---
if menu == "🔍 Ispezione":
    st.title("🔍 Nuova Perizia")
    targa = st.selectbox("Seleziona Veicolo:", TARGHE_GSSA)
    video = st.file_uploader("Carica Video", type=["mp4", "mov"])
    
    if st.button("🚀 AVVIA ANALISI"):
        if video:
            with st.spinner("Analisi e sincronizzazione con Google Sheets..."):
                with open("temp.mp4", "wb") as f: f.write(video.read())
                frames = estrai_frame("temp.mp4")
                
                # Cerca lo storico nel foglio
                row = df[df["Targa"] == targa].iloc[0]
                storico = str(row["Report"]) if pd.notna(row["Report"]) else ""
                
                model = genai.GenerativeModel("gemini-1.5-flash")
                if storico == "" or "NESSUN DANNO" in storico.upper():
                    prompt = f"Prima perizia per {targa}. Elenca ogni danno zonale."
                else:
                    prompt = f"Confronto per {targa}. Storico: {storico}. Se non ci sono nuovi danni rispondi esattamente 'NESSUN NUOVO DANNO'."

                response = model.generate_content([prompt] + [{"mime_type": "image/jpeg", "data": f['bytes']} for f in frames])
                ris = response.text.strip()
                
                nuovi = "NESSUN NUOVO DANNO" not in ris.upper()
                testo_f = ris if nuovi or storico == "" else "✅ Ispezione apposto, nessun nuovo danno rilevato."
                
                # AGGIORNA IL DATAFRAME E CARICA SU GSHEETS
                df.loc[df["Targa"] == targa, "Report"] = ris if nuovi or storico == "" else storico
                df.loc[df["Targa"] == targa, "Data"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                df.loc[df["Targa"] == targa, "Stato"] = "🚨 DANNI" if nuovi or storico == "" else "✅ OK"
                
                conn.update(worksheet="ispezioni", data=df)
                st.success("Dati salvati permanentemente su Google Sheets!")
                
                st.markdown(f"### Risultato {targa}:")
                st.write(testo_f)
                
                pdf = crea_pdf_bytes(targa, testo_f, nuovi)
                st.download_button("📥 Scarica PDF Ufficiale", data=pdf, file_name=f"Report_{targa}.pdf")

# --- 2. ARCHIVIO ---
elif menu == "📂 Archivio":
    st.title("📂 Archivio Storico")
    targa = st.selectbox("Cerca Targa:", TARGHE_GSSA)
    res = df[df["Targa"] == targa].iloc[0]
    st.write(f"**Stato:** {res['Stato']}")
    st.write(f"**Ultimo Controllo:** {res['Data']}")
    st.info(res['Report'] if res['Report'] else "Nessuna perizia registrata.")

# --- 3. AREA ADMIN ---
elif menu == "👑 Area Admin":
    st.title("👑 Pannello Amministratore")
    pw = st.text_input("Password Admin", type="password")
    if pw == "GSSA2026":
        st.subheader("Stato Flotta in tempo reale (da Google Sheets)")
        st.dataframe(df, use_container_width=True)
        st.download_button("📊 Scarica Excel", data=df.to_csv(index=False).encode('utf-8'), file_name="flotta_gssa.csv")
    elif pw:
        st.error("Accesso negato")

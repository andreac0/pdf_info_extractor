import streamlit as st
import json
import base64
import requests
import time
import pandas as pd
import io
import xlsxwriter

# --- Configuration ---
MODEL_NAME = "gemini-2.5-flash"

EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "nome": {"type": "STRING"},
        "cognome": {"type": "STRING"},
        "statoCivile": {"type": "STRING"},
        "invaliditaConiuge": {"type": "BOOLEAN"},
        "numeroFigliCarico": {"type": "INTEGER"},
        "numeroFigliInvalidi": {"type": "INTEGER"},
        "numeroAltriFamiliariACarico": {"type": "INTEGER"},
        "coniugeACarico": {"type": "BOOLEAN"},
    },
    "propertyOrdering": [
        "nome", "cognome", "statoCivile",
        "coniugeACarico", "invaliditaConiuge",
        "numeroFigliCarico", "numeroFigliInvalidi",
        "numeroAltriFamiliariACarico"
    ]
}

SYSTEM_PROMPT = "Sei un sistema di estrazione dati specializzato in documenti di autocertificazione."
USER_QUERY = "Estrai le seguenti informazioni chiave sul richiedente e il suo nucleo familiare:"


# --- Utility Functions ---
def convert_file_to_base64(file_obj):
    file_obj.seek(0)
    file_bytes = file_obj.read()
    return base64.b64encode(file_bytes).decode("utf-8")


def extract_data_with_gemini(base64_data, mime_type, api_key):
    max_retries = 5
    initial_delay = 1

    API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": USER_QUERY},
                    {"inlineData": {"mimeType": mime_type, "data": base64_data}}
                ]
            }
        ],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": EXTRACTION_SCHEMA
        }
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(API_URL, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
            resp.raise_for_status()
            result = resp.json()
            json_text = result["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(json_text)

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(initial_delay * (2 ** attempt))
            else:
                st.error(f"Errore API definitivo: {e}")
                return None
    return None


# --- Streamlit UI ---
st.set_page_config(page_title="Document Data Extractor", layout="wide")

# Initialize session state
if "df" not in st.session_state:
    st.session_state.df = None

st.markdown('<h1 class="main-header">📄 Estrazione dati da Documenti</h1>', unsafe_allow_html=True)
st.write("Carica uno o più documenti PDF/JPG/PNG per estrarre informazioni strutturate.")

# Sidebar API Key
with st.sidebar:
    st.title("Configurazione API")
    api_key = st.text_input("Chiave API:", type="password")
    final_api_key = api_key or ""

# Uploader
uploaded_files = st.file_uploader(
    "Carica uno o più file",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True
)

# --- RUN EXTRACTION ONLY IF NEW FILES ARE UPLOADED AND DF IS EMPTY ---
if uploaded_files and st.session_state.df is None:

    if not final_api_key:
        st.warning("⚠️ Nessuna API key fornita.")

    all_extracted_data = []

    with st.spinner(f"Analisi di {len(uploaded_files)} documenti in corso..."):
        for file in uploaded_files:

            base64_data = convert_file_to_base64(file)
            mime_type = file.type or "application/octet-stream"

            extracted = extract_data_with_gemini(base64_data, mime_type, final_api_key)

            if extracted:
                extracted["Nome File"] = file.name
                all_extracted_data.append(extracted)
                st.success(f"Dati estratti da {file.name}")
            else:
                st.error(f"Impossibile estrarre dati da {file.name}")

    if all_extracted_data:
        df = pd.DataFrame(all_extracted_data)

        # Reorder and rename columns
        display_columns = [
            "Nome File", "nome", "cognome", "statoCivile",
            "coniugeACarico", "invaliditaConiuge",
            "numeroFigliCarico", "numeroFigliInvalidi",
            "numeroAltriFamiliariACarico"
        ]

        for c in display_columns:
            if c not in df.columns:
                df[c] = None

        df = df[display_columns]

        df.columns = [
            "Nome File", "Nome", "Cognome", "Stato Civile",
            "Coniuge a Carico", "Invalidità Coniuge",
            "N. Figli a Carico", "N. Figli Invalidi",
            "N. Altri Familiari a Carico"
        ]

        st.session_state.df = df
    else:
        st.warning("Nessun dato estratto.")


# --- IF DF EXISTS, SHOW TABLE + DOWNLOAD WITHOUT RERUN ---
if st.session_state.df is not None:

    df = st.session_state.df
    st.subheader("📊 Risultati estratti")
    st.table(df)

    # CSV download
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, sep=";", index=False, encoding="utf-8")

    st.download_button(
        label="⬇️ Scarica CSV",
        data=csv_buffer.getvalue(),
        file_name="dati_estratti.csv",
        mime="text/csv"
    )

    # Excel download
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Dati Estratti")

    excel_buffer.seek(0)
    st.download_button(
        label="⬇️ Scarica Excel (XLSX)",
        data=excel_buffer,
        file_name="dati_estratti.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --- Reset button ---
st.button("🔄 Reset", on_click=lambda: st.session_state.update({"df": None}))

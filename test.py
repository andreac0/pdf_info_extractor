import streamlit as st
import json
import base64
import requests
import time
import pandas as pd
import io

# --- Configuration (Base Definitions) ---
# Utilizziamo il nome del modello stabile 'gemini-2.5-flash'.
MODEL_NAME = "gemini-2.5-flash"

# Define the JSON schema for structured output (MANDATORY for reliable data extraction)
EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "nome": {"type": "STRING", "description": "Nome dell'individuo. Se non trovato, usare una stringa vuota."},
        "cognome": {"type": "STRING", "description": "Cognome dell'individuo. Se non trovato, usare una stringa vuota."},
        # "dataNascita": {"type": "STRING", "description": "Data di nascita nel formato GG/MM/AAAA. Se non trovata, usare una stringa vuota."},
        # "nomeConiuge": {"type": "STRING", "description": "Nome o Cognome del coniuge/partner. Se non trovato, usare una stringa vuota."},
        "invaliditaConiuge": {"type": "BOOLEAN", "description": "True se viene esplicitamente dichiarata l'invalidità o lo stato di invalido del coniuge (e.g., 'invalido permanente'), altrimenti False."},
        "numeroFigliCarico": {"type": "INTEGER", "description": "Il numero totale di figli a carico dichiarati. Se non specificato o trovato, usare 0."},
        "invaliditaFigli": {"type": "BOOLEAN", "description": "True se viene dichiarato che uno o più figli sono invalidi."},
        "infoFigliInvalidi": {"type": "STRING", "description": "Nomi e dettagli dei figli dichiarati invalidi. Se nessuno, stringa vuota."}
    },
    "propertyOrdering": ["nome", "cognome",  "invaliditaConiuge", "numeroFigliCarico", "invaliditaFigli", "infoFigliInvalidi"]
}

# --- Prompts ---
SYSTEM_PROMPT = "Sei un sistema di estrazione dati specializzato in documenti di autocertificazione. Analizza il documento fornito (PDF o immagine) e compila scrupolosamente tutti i campi richiesti nel formato JSON specificato."
USER_QUERY = "Estrai le seguenti informazioni chiave sul richiedente e il suo nucleo familiare, indipendentemente dal fatto che provengano da testo normale, campi modulo o immagini:"

# --- Utility Functions ---

def convert_file_to_base64(file_obj):
    """Reads the uploaded Streamlit file and returns its base64 encoded string."""
    file_obj.seek(0)
    file_bytes = file_obj.read()
    return base64.b64encode(file_bytes).decode('utf-8')

def extract_data_with_gemini(base64_data, mime_type, api_key):
    """
    Simulates an SDK-style call to the Gemini API using requests for structured 
    multimodal extraction. Includes exponential backoff for resilience.
    
    The API key is now passed as an argument.
    """
    max_retries = 5
    initial_delay = 1
    
    API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": USER_QUERY},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64_data
                        }
                    }
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
            # Perform the API request
            response = requests.post(
                API_URL, 
                headers={'Content-Type': 'application/json'}, 
                data=json.dumps(payload)
            )
            response.raise_for_status()
            
            # Successful response, parse JSON text from the model's response
            result = response.json()
            # Navigate the JSON structure to find the generated JSON string
            json_text = result['candidates'][0]['content']['parts'][0]['text']
            
            # Parse the structured JSON output
            return json.loads(json_text)
            
        except requests.exceptions.RequestException as e:
            # Handle specific API errors, including connection issues and rate limits
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                # Log final error but return None for UI handling
                st.error(f"Errore API definitivo: Impossibile estrarre i dati. {e}")
                return None
        except (KeyError, json.JSONDecodeError) as e:
            # Handle model output structure errors
            st.error(f"Errore nella decodifica o struttura della risposta dell'API: {e}")
            return None
    return None

# --- Streamlit UI ---
st.set_page_config(page_title="Document Data Extractor", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background-color: #f0f2f6;
    }
    .main-header {
        color: #1f78b4;
        font-weight: 600;
        text-align: center;
        margin-bottom: 20px;
    }
    .stTable {
        border-radius: 0.5rem;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<h1 class="main-header">📄 Estrazione dati da Documenti</h1>', unsafe_allow_html=True)
st.write("Carica uno o più documenti (PDF, PNG, JPG) di autocertificazione per estrarre informazioni strutturate.")

# --- API Key Input in Sidebar ---
with st.sidebar:
    st.title("Configurazione API")
    user_api_key = st.text_input(
        "Chiave API:",
        type="password",
        help="La chiave API è necessaria per l'autenticazione. Lasciare vuoto se si esegue in un ambiente Canvas (che la fornisce automaticamente)."
    )
    final_api_key = user_api_key or "" # Use the user input, or empty string for Canvas environment

# --- File Uploader ---
uploaded_files = st.file_uploader(
    "Carica uno o più file (PDF o Immagini)", 
    type=["pdf", "png", "jpg", "jpeg"], 
    accept_multiple_files=True, 
    key="file_uploader"
)

if uploaded_files:
    
    # Check if a key is available (either provided by user or expected from environment)
    if not final_api_key:
         st.warning("⚠️ Chiave API Gemini mancante. L'estrazione procederà solo se l'ambiente di esecuzione la fornisce automaticamente.")
    
    all_extracted_data = []
    
    with st.spinner(f"Analisi di {len(uploaded_files)} PDF in corso con AI..."):
        
        # Itera su ciascun file caricato
        for i, uploaded_file in enumerate(uploaded_files):
            st.markdown(f"**Analisi del file {i+1}/{len(uploaded_files)}: {uploaded_file.name}**")
            
            try:
                # 1. Convert file to Base64
                base64_data = convert_file_to_base64(uploaded_file)
                
                # Determine mime type
                mime_type = uploaded_file.type
                # Fallback if Streamlit doesn't guess it (e.g. sometimes it might be None related, though usually reliable)
                if not mime_type:
                    if uploaded_file.name.lower().endswith(".pdf"):
                        mime_type = "application/pdf"
                    elif uploaded_file.name.lower().endswith((".png")):
                        mime_type = "image/png"
                    elif uploaded_file.name.lower().endswith((".jpg", ".jpeg")):
                        mime_type = "image/jpeg"
                    else:
                        mime_type = "application/octet-stream" # Default

                # 2. Call the extraction function, passing the API key and mime type
                extracted_info = extract_data_with_gemini(base64_data, mime_type, final_api_key)

                if extracted_info:
                    # 3. Aggiungi il nome del file ai dati estratti
                    extracted_info['Nome File'] = uploaded_file.name
                    all_extracted_data.append(extracted_info)
                    st.success(f"Dati estratti con successo da {uploaded_file.name}.")
                else:
                    st.error(f"Impossibile estrarre le informazioni da {uploaded_file.name}.")
                    
            except Exception as e:
                st.error(f"Si è verificato un errore inaspettato durante l'analisi di {uploaded_file.name}: {e}")

    # Visualizzazione e download dei risultati combinati
    if all_extracted_data:
        st.subheader("✅ Risultati estratti (Tabella combinata)")
        
        # Crea il DataFrame combinato
        df = pd.DataFrame(all_extracted_data)
        
        # Riordina e rinomina le colonne per la visualizzazione
        # Nota: Rimosse colonne commentate nello schema per evitare errori
        display_columns = ['Nome File', 'nome', 'cognome', 'invaliditaConiuge', 'numeroFigliCarico', 'invaliditaFigli', 'infoFigliInvalidi']
        
        # Gestione colonne mancanti se il modello non le restituisce (sicurezza)
        for col in display_columns:
            if col not in df.columns:
                df[col] = None # o valore default appropriato
                
        df = df[display_columns]

        df.columns = [
            "Nome File", "Nome", "Cognome", 
            "Invalidità Coniuge", "N. Figli a Carico", "Invalidità Figli", "Info Figli Invalidi"
        ]
        
        st.table(df)

        # Download CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False, sep=';', encoding='utf-8')
        
        st.download_button(
            label="⬇️ Scarica CSV Combinato",
            data=csv_buffer.getvalue(),
            file_name="dati_estratti_gemini_combinati.csv",
            mime="text/csv",
            help="Scarica i dati estratti da tutti i PDF in formato CSV (separatore ';')"
        )
    else:
        st.warning("Nessun dato è stato estratto con successo.")


st.info("Nota: Questa app utilizza AI per l'analisi multimodale di documenti (PDF e immagini).")
# 2. Conecta ao Google Sheets com validação de credenciais
def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    gcp_key = os.environ.get("GCP_SA_KEY")
    if not gcp_key:
        raise ValueError("ERRO CRÍTICO: O Secret 'GCP_SA_KEY' está vazio ou não foi configurado no GitHub!")
        
    try:
        sa_info = json.loads(gcp_key)
    except json.JSONDecodeError as e:
        raise ValueError("ERRO CRÍTICO: O Secret 'GCP_SA_KEY' não contém um JSON válido. Recopie todo o conteúdo do arquivo .json baixado do Google Cloud.") from e

    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise ValueError("ERRO CRÍTICO: O Secret 'SHEET_ID' não foi encontrado no GitHub!")
        
    return client.open_by_key(sheet_id).sheet1

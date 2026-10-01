import os
import json
import asyncio
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright

# 1. Calcula o código do mês no formato do Skyscanner (ex: '2610' para Out/2026)
def obter_tres_proximos_meses():
    hoje = datetime.now()
    meses_info = []
    
    for offset in range(3):
        m = hoje.month + offset
        y = hoje.year
        while m > 12:
            m -= 12
            y += 1
        
        yy = str(y)[-2:]
        mm = f"{m:02d}"
        oym = f"{yy}{mm}"
        label_mes = f"{mm}/{y}"
        meses_info.append((label_mes, oym))
        
    return meses_info

# 2. Conecta ao Google Sheets com tratamento de erro de credenciais
def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    gcp_key = os.environ.get("GCP_SA_KEY")
    if not gcp_key:
        raise ValueError("ERRO CRÍTICO: O Secret 'GCP_SA_KEY' não foi encontrado ou está vazio neste repositório!")
        
    try:
        sa_info = json.loads(gcp_key)
    except json.JSONDecodeError as e:
        raise ValueError("ERRO CRÍTICO: O Secret 'GCP_SA_KEY' não é um JSON válido. Verifique se copiou todo o conteúdo do arquivo .json.") from e

    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise ValueError("ERRO CRÍTICO: O Secret 'SHEET_ID' não foi encontrado neste repositório!")
        
    return client.open_by_key(sheet_id).sheet1

# 3. Verifica se a chave na célula G1 da planilha está como LIGADO
def verificar_status_ativo(sheet):
    try:
        status = sheet.acell('G1').value
        if status and status.strip().upper() == "LIGADO":
            return True
        print(f"Status na célula G1 é '{status}'. Apenas 'LIGADO' executa a busca.")
        return False
    except Exception as e:
        print(f"Aviso ao ler célula de status: {e}. Executando por padrão.")
        return True

# 4. Extração dos dados no Skyscanner
async def extrair_voos_mes(page, origem, destino, label_mes, oym):
    url = f"https://www.skyscanner.com.br/transporte/passagens-aereas/{origem}/{destino}/?adultsv2=1&cabinclass=economy&childrenv2=&ref=home&rtn=0&outboundaltsenabled=false&inboundaltsenabled=false&oym={oym}&selectedoday=01"
    
    print(f"Pesquisando período {label_mes} (oym={oym})...")
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(5000)
    
    voos_extraidos = []
    data_coleta = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    cards = await page.query_selector_all("[class*='Ticket_paper'], [class*='ItineraryCard'], [class*='CalendarCell_cell']")
    
    for card in cards:
        try:
            preco_el = await card.query_selector("[class*='Price_main'], [class*='Price'], [class*='price']")
            duracao_el = await card.query_selector("[class*='Duration'], [class*='DurationText']")
            data_el = await card.query_selector("[class*='LegInfo_date'], [class*='LegInfo'], [class*='day-number']")
            
            preco = await preco_el.inner_text() if preco_el else None
            duracao = await duracao_el.inner_text() if duracao_el else "Direto/Variado"
            data = await data_el.inner_text() if data_el else "Mês Flexível"
            
            if preco:
                voos_extraidos.append([data_coleta, label_mes, data.strip(), preco.strip(), duracao.strip()])
        except Exception:
            continue
            
    return voos_extraidos

async def main():
    sheet = conectar_google_sheets()
    
    # Valida botão LIGADO/DESLIGADO na planilha
    if not verificar_status_ativo(sheet):
        print("Automação desativada na planilha (célula G1 diferente de 'LIGADO'). Finalizando sem buscar.")
        return

    origem = "bsb"   # Brasília
    destino = "the"  # Teresina
    
    meses_para_consultar = obter_tres_proximos_meses()
    todos_os_dados = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        for label_mes, oym in meses_para_consultar:
            dados_mes = await extrair_voos_mes(page, origem, destino, label_mes, oym)
            todos_os_dados.extend(dados_mes)
            await page.wait_for_timeout(3000)
            
        await browser.close()
    
    if todos_os_dados:
        if not sheet.get_all_values():
            sheet.append_row(["Data da Coleta", "Mês Referência", "Dia/Data Voo", "Preço", "Duração"])
            
        for linha in todos_os_dados:
            sheet.append_row(linha)
            
        print(f"Sucesso! {len(todos_os_dados)} registros gravados na planilha.")
    else:
        print("Nenhum preço encontrado nas buscas do período.")

if __name__ == "__main__":
    asyncio.run(main())

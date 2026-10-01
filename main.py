import os
import json
import asyncio
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright

# 1. Calcula o rótulo dos 3 próximos meses a partir do mês atual
def obter_rotulos_meses():
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

# 2. Conecta ao Google Sheets com validação das chaves
def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    gcp_key = os.environ.get("GCP_SA_KEY")
    if not gcp_key:
        raise ValueError("ERRO CRÍTICO: Secret 'GCP_SA_KEY' não foi encontrado no GitHub Actions.")
        
    try:
        sa_info = json.loads(gcp_key)
    except json.JSONDecodeError as e:
        raise ValueError("ERRO CRÍTICO: Secret 'GCP_SA_KEY' não contém um JSON válido.") from e

    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
    
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise ValueError("ERRO CRÍTICO: Secret 'SHEET_ID' não foi encontrado no GitHub Actions.")
        
    return client.open_by_key(sheet_id).sheet1

# 3. Verifica e inicializa o status na célula G1
def verificar_status_ativo(sheet):
    try:
        val = sheet.acell('G1').value
        if not val or val.strip() == "":
            sheet.update(range_name='F1:G1', values=[['Status Automação:', 'LIGADO']])
            return True
        return val.strip().upper() == "LIGADO"
    except Exception as e:
        print(f"Aviso ao verificar status em G1: {e}. Executando por padrão.")
        return True

# 4. Raspa os dados de preço visíveis na página ativa do calendário
async def extrair_cards_visiveis(page, label_mes):
    await page.wait_for_timeout(4000)
    data_coleta = datetime.now().strftime("%d/%m/%Y %H:%M")
    voos_extraidos = []
    
    cards = await page.query_selector_all(
        "[class*='Ticket_paper'], [class*='ItineraryCard'], [class*='CalendarCell_cell'], [class*='day-cell']"
    )
    print(f"   ├─ [{label_mes}] {len(cards)} elementos de calendário/preço encontrados.")
    
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

# 5. Navegação Interativa da Interface
async def executar_navegacao_interativa(page, origem, destino, meses_info):
    todos_os_dados = []
    url_base = f"https://www.skyscanner.com.br/transporte/passagens-aereas/{origem}/{destino}/"
    
    print(f"🌐 1. Abrindo página de busca da rota: {url_base}")
    await page.goto(url_base, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(5000)
    
    # Tenta aceitar cookies se o banner aparecer
    try:
        btn_cookie = await page.query_selector("button:has-text('Aceitar'), button:has-text('OK'), #accept-cookies")
        if btn_cookie:
            await btn_cookie.click()
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    # Tenta abrir o seletor de datas e escolher 'Mês inteiro' / 'Datas flexíveis'
    navegou_com_sucesso = False
    try:
        print("👆 2. Interagindo com o seletor de datas flexíveis...")
        # Clica no seletor de data de ida
        btn_data = await page.query_selector("[data-testid='depart-btn'], button[aria-label*='Data'], [class*='DateInput']")
        if btn_data:
            await btn_data.click()
            await page.wait_for_timeout(1500)
            
        # Clica na aba 'Mês inteiro' ou 'Datas flexíveis'
        aba_flexivel = await page.query_selector("button:has-text('Mês inteiro'), button:has-text('Flexível'), [data-testid='whole-month-tab']")
        if aba_flexivel:
            await aba_flexivel.click()
            await page.wait_for_timeout(2000)
            
            # Clica no botão de busca/aplicar
            btn_buscar = await page.query_selector("button[type='submit'], button:has-text('Buscar voos'), button:has-text('Ver voos')")
            if btn_buscar:
                await btn_buscar.click()
                await page.wait_for_timeout(6000)
                navegou_com_sucesso = True
    except Exception as err:
        print(f"⚠️ Aviso na interação do menu: {err}. Alternando para navegação direta de meses.")

    # Se a navegação interativa inicial não abriu a visão mensal, usa a URL direta da visão flexível do mês atual
    if not navegou_com_sucesso:
        label_m1, oym_m1 = meses_info[0]
        url_flexivel = f"{url_base}?adultsv2=1&cabinclass=economy&rtn=0&oym={oym_m1}&selectedoday=01"
        print(f"🔗 Acessando visão mensal flexível direta do mês {label_m1}...")
        await page.goto(url_flexivel, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(6000)

    # Coleta Mês 1
    label_m1, _ = meses_info[0]
    dados_m1 = await extrair_cards_visiveis(page, label_m1)
    todos_os_dados.extend(dados_m1)

    # Navega para o Mês 2 e Mês 3 clicando no botão 'Próximo Mês' na interface
    for idx in range(1, 3):
        label_mes, oym = meses_info[idx]
        print(f"▶ 3.{idx} Avançando para o próximo mês ({label_mes})...")
        
        clicou_proximo = False
        try:
            # Tenta clicar na seta/botão de próximo mês no calendário
            btn_proximo = await page.query_selector(
                "button[aria-label*='Próximo'], button[aria-label*='Next'], [data-testid='next-month-btn'], button:has-text('>')"
            )
            if btn_proximo and await btn_proximo.is_visible():
                await btn_proximo.click()
                await page.wait_for_timeout(5000)
                clicou_proximo = True
        except Exception as err:
            print(f"   └─ Botão de próximo mês não clicável: {err}")

        # Fallback de URL caso o botão de próximo mês não tenha respondido ao clique
        if not clicou_proximo:
            url_mes = f"{url_base}?adultsv2=1&cabinclass=economy&rtn=0&oym={oym}&selectedoday=01"
            print(f"   └─ Carregando página do mês {label_mes} via URL de fallback...")
            await page.goto(url_mes, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(5000)

        dados_mes = await extrair_cards_visiveis(page, label_mes)
        todos_os_dados.extend(dados_mes)

    return todos_os_dados

async def main():
    print("🚀 Iniciando automação Skyscanner com navegação de datas flexíveis...")
    sheet = conectar_google_sheets()
    
    if not verificar_status_ativo(sheet):
        print("⏸️ Automação desativada na planilha (Célula G1 diferente de 'LIGADO'). Encerrando.")
        return

    origem = "bsb"   # Brasília
    destino = "the"  # Teresina
    meses_info = obter_rotulos_meses() # Mês atual + 2 meses seguintes
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="pt-BR"
        )
        
        page = await context.new_page()
        todos_os_dados = await executar_navegacao_interativa(page, origem, destino, meses_info)
        await browser.close()
    
    if todos_os_dados:
        # Garante o cabeçalho caso a célula A1 esteja vazia
        if not sheet.acell('A1').value:
            sheet.insert_row(["Data da Coleta", "Mês Referência", "Dia/Data Voo", "Preço", "Duração"], index=1)
            
        sheet.append_rows(todos_os_dados)
        print(f"✅ Sucesso! {len(todos_os_dados)} registros de voos gravados na planilha.")
    else:
        print("⚠️ Nenhum preço encontrado nas buscas do período.")

if __name__ == "__main__":
    asyncio.run(main())

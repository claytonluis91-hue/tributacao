import streamlit as st
import pandas as pd
import plotly.express as px
import io
import PyPDF2
import re
from engine_tributario import (
    DadosMes, 
    ConfigTributaria, 
    simular_12_meses
)
from db import init_db, salvar_simulacao, listar_simulacoes

# Inicializar DB
init_db()

st.set_page_config(page_title="Simulador Tributário 12 Meses", layout="wide")

st.title("📊 Simulador e Comparador Tributário (12 Meses)")
st.markdown("Comparativo de carga tributária entre **Simples Nacional**, **Lucro Presumido** e **Lucro Real**.")

# ---------------------------------------------------------
# EXTRAÇÃO DE DADOS
# ---------------------------------------------------------
def extrair_dados_pgdas(file_bytes):
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        rbt12 = 0.0
        folha = 0.0
        
        # Buscar RBT12 - "Receita bruta acumulada nos doze meses anteriores ao PA (RBT12)"
        match_rbt12 = re.search(r'\(RBT12\)\s+([\d\.]+,\d{2})', text)
        if match_rbt12:
            valor_str = match_rbt12.group(1).replace(".", "").replace(",", ".")
            rbt12 = float(valor_str)
            
        # Buscar Folha - "Total de Folhas de Salários Anteriores (R$)"
        match_folha = re.search(r'Total de Folhas de Salários Anteriores \(R\$\)\s+R\$\s+([\d\.]+,\d{2})', text)
        if match_folha:
            valor_str = match_folha.group(1).replace(".", "").replace(",", ".")
            folha = float(valor_str)
            
        return rbt12, folha
    except Exception as e:
        st.error(f"Erro ao extrair dados do PGDAS: {e}")
        return 0.0, 0.0

# ---------------------------------------------------------
# SIDEBAR - CONFIGURAÇÕES FIXAS
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configurações Globais")
    
    st.subheader("Encargos e Folha")
    aliquota_rat = st.number_input("Alíquota RAT (%)", value=2.0, step=0.5) / 100
    fap = st.number_input("FAP", value=1.0, step=0.1)
    aliquota_terceiros = st.number_input("Terceiros (%)", value=5.8, step=0.1) / 100
    
    st.subheader("Simples Nacional")
    is_anexo_iv = st.checkbox("Anexo IV (INSS Patronal por Fora)?", value=False)
    fator_r_sujeito = st.checkbox("Sujeito ao Fator R (Anexo III vs V)?", value=True)
    
    st.subheader("Lucro Presumido e Real")
    presuncao_irpj = st.number_input("Presunção IRPJ (%)", value=32.0, step=1.0) / 100
    presuncao_csll = st.number_input("Presunção CSLL (%)", value=32.0, step=1.0) / 100
    aliquota_issqn = st.number_input("Alíquota ISSQN (%)", value=0.0, step=0.5) / 100

config = ConfigTributaria(
    aliquota_rat=aliquota_rat,
    fap=fap,
    aliquota_terceiros=aliquota_terceiros,
    is_anexo_iv=is_anexo_iv,
    fator_r_sujeito=fator_r_sujeito,
    presuncao_irpj=presuncao_irpj,
    presuncao_csll=presuncao_csll,
    aliquota_issqn=aliquota_issqn
)


# ---------------------------------------------------------
# INPUTS GLOBAIS NA TELA PRINCIPAL
# ---------------------------------------------------------
st.markdown("### 📥 Importação de PGDAS")
arquivo_pgdas = st.file_uploader("Envie o Extrato do PGDAS (PDF) para preencher automaticamente", type=["pdf"])

if "pgdas_rbt12" not in st.session_state:
    st.session_state["pgdas_rbt12"] = 0.0
if "pgdas_folha" not in st.session_state:
    st.session_state["pgdas_folha"] = 0.0

if arquivo_pgdas is not None:
    # Apenas tenta ler se for diferente do que já está em memória para evitar recálculos contínuos
    if "last_uploaded_file" not in st.session_state or st.session_state["last_uploaded_file"] != arquivo_pgdas.name:
        rbt, folha = extrair_dados_pgdas(arquivo_pgdas.read())
        if rbt > 0:
            st.session_state["pgdas_rbt12"] = rbt
            st.session_state["pgdas_folha"] = folha
            st.session_state["last_uploaded_file"] = arquivo_pgdas.name
            st.success(f"Dados extraídos com sucesso! RBT12: R$ {rbt:,.2f} | Folha: R$ {folha:,.2f}")

st.divider()

st.markdown("### Histórico Acumulado (Últimos 12 Meses)")
col_rbt, col_folha = st.columns(2)
with col_rbt:
    rbt12_inicial = st.number_input("RBT12 Acumulado (Anterior) - Deixe 0 se nova", value=st.session_state["pgdas_rbt12"], step=10000.0)
with col_folha:
    folha12m_inicial = st.number_input("Folha 12M (Anterior) - Deixe 0 se nova", value=st.session_state["pgdas_folha"], step=10000.0)

st.divider()
tab_projecao, tab_mensal = st.tabs(["📅 Projeção 12 Meses", "⏱️ Simulação Mensal Rápida"])

# ==========================================
# FUNÇÕES E IMPORTS AUXILIARES
# ==========================================
from openpyxl.styles import Font, PatternFill
def gerar_excel(resultados, dados_input):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        
        # Tabela 0: Resumo Comparativo
        resumo_data = []
        for r in resultados:
            vencedor_mes = min({"Simples": r.total_sn, "Presumido": r.total_lp, "Real": r.total_lr}.items(), key=lambda x: x[1])
            resumo_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "Total Simples Nacional": r.total_sn,
                "Total Lucro Presumido": r.total_lp,
                "Total Lucro Real": r.total_lr,
                "Melhor Regime": vencedor_mes[0],
                "Economia (Diferença para o 2º)": sorted([r.total_sn, r.total_lp, r.total_lr])[1] - vencedor_mes[1]
            })
        df_resumo = pd.DataFrame(resumo_data)
        df_resumo.to_excel(writer, sheet_name="Resumo Comparativo", index=False)

        # Tabela 1: Simples Nacional
        sn_data = []
        for r in resultados:
            sn_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "RBT12 Calculado": r.sn_rbt12,
                "Faixa Anexo": f"Faixa {r.sn_faixa}",
                "Alíquota Efetiva": r.sn_aliquota_efetiva,
                "Valor Total DAS": r.sn_total_das,
                "IRPJ": r.sn_valor_irpj,
                "CSLL": r.sn_valor_csll,
                "COFINS": r.sn_valor_cofins,
                "PIS/Pasep": r.sn_valor_pis,
                "CPP (INSS)": r.sn_valor_cpp,
                "ISS": r.sn_valor_iss,
                "INSS Extra (Folha)": r.sn_encargos - r.sn_valor_cpp,
                "Total Mês": r.total_sn
            })
        pd.DataFrame(sn_data).to_excel(writer, sheet_name="Simples Nacional", index=False)

        # Tabela 2: Lucro Presumido
        lp_data = []
        for r in resultados:
            lp_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "Base IRPJ": r.lp_base_irpj,
                "Alíq. IRPJ/CSLL": "15% / 9%",
                "IRPJ/CSLL Normal": r.lp_irpj_csll_normal,
                "Adicional IRPJ (10%)": r.lp_adicional_irpj,
                "Alíq. PIS/COFINS": "3.65%",
                "PIS/COFINS": r.lp_consumo - r.lp_valor_iss,
                "ISS": r.lp_valor_iss,
                "INSS Patronal": r.lp_encargos,
                "Total Mês": r.total_lp
            })
        pd.DataFrame(lp_data).to_excel(writer, sheet_name="Lucro Presumido", index=False)

        # Tabela 3: Lucro Real
        lr_data = []
        for r in resultados:
            lr_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "LAIR": r.lr_lair,
                "Alíq. IRPJ/CSLL": "15% / 9%",
                "IRPJ/CSLL Normal": r.lr_irpj_csll_normal,
                "Adicional IRPJ (>20k)": r.lr_adicional_irpj,
                "Alíq. PIS/COFINS": "9.25% (Não Cumulativo)",
                "PIS/COFINS Liq": r.lr_consumo - r.lr_valor_iss,
                "ISS": r.lr_valor_iss,
                "INSS Patronal": r.lr_encargos,
                "Total Mês": r.total_lr
            })
        pd.DataFrame(lr_data).to_excel(writer, sheet_name="Lucro Real", index=False)
        
        # Formatando as planilhas
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
                cell.fill = header_fill
            
            for col in worksheet.columns:
                max_length = 0
                column = col[0].column_letter
                header_name = str(col[0].value).lower()
                for i, cell in enumerate(col):
                    try:
                        if i > 0 and isinstance(cell.value, (int, float)):
                            if "alíquota" in header_name or "fator r" in header_name:
                                cell.number_format = '0.00%'
                            elif "mês" not in header_name:
                                cell.number_format = r'_-\R$* #,##0.00_-;-\R$* #,##0.00_-;_-\R$* "-"??_-;_-@_-'
                        if cell.value:
                            val_len = len(str(cell.value))
                            if val_len > max_length:
                                max_length = val_len
                    except:
                        pass
                adjusted_width = max(max_length + 2, 14)
                worksheet.column_dimensions[column].width = adjusted_width
    return output.getvalue()

def formata_reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def renderizar_impacto_folha(resultados, config_global):
    st.markdown("### 📈 Impacto da Folha de Pagamento")
    st.markdown("Esta seção isola os custos associados aos empregados e o benefício/risco do **Fator R** (para Anexo III vs V do Simples).")
    
    tot_sn_cpp = sum(r.sn_valor_cpp for r in resultados)
    tot_sn_extra = sum(r.sn_encargos - r.sn_valor_cpp for r in resultados)
    tot_lp_enc = sum(r.lp_encargos for r in resultados)
    tot_lr_enc = sum(r.lr_encargos for r in resultados)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**Simples Nacional**\nCPP na DAS: {formata_reais(tot_sn_cpp)}\nINSS Extra: {formata_reais(tot_sn_extra)}\n**Total: {formata_reais(tot_sn_cpp + tot_sn_extra)}**")
    with col2:
        st.warning(f"**Lucro Presumido**\nINSS Patronal (RAT/Terceiros):\n**Total: {formata_reais(tot_lp_enc)}**")
    with col3:
        st.error(f"**Lucro Real**\nINSS Patronal (RAT/Terceiros):\n**Total: {formata_reais(tot_lr_enc)}**")
        
    df_fator_r = pd.DataFrame([{"Mês": r.mes, "Fator R Calculado": f"{r.sn_fator_r*100:.2f}%", "Faixa/Anexo": f"Faixa {r.sn_faixa}"} for r in resultados])
    with st.expander("Verificar Fator R Mês a Mês (Simples Nacional)"):
        st.dataframe(df_fator_r, use_container_width=True, hide_index=True)

def renderizar_detalhes_tributos(resultados):
    st.markdown("### 🔍 Detalhamento de Tributos")
    tab_efetiva, tab_nominal = st.tabs(["📊 Alíquotas Efetivas (s/ Faturamento Bruto)", "📜 Alíquotas Nominais"])
    
    tot_fat = sum(r.faturamento for r in resultados)
    if tot_fat == 0:
        tot_fat = 1  # prevent div/0
        
    sn_irpj = sum(r.sn_valor_irpj for r in resultados)
    sn_csll = sum(r.sn_valor_csll for r in resultados)
    sn_cofins = sum(r.sn_valor_cofins for r in resultados)
    sn_pis = sum(r.sn_valor_pis for r in resultados)
    sn_cpp = sum(r.sn_valor_cpp for r in resultados)
    sn_iss = sum(r.sn_valor_iss for r in resultados)
    sn_extra = sum(r.sn_encargos - r.sn_valor_cpp for r in resultados)
    sn_total = sum(r.total_sn for r in resultados)
    
    lp_fed = sum(r.lp_federal for r in resultados)
    lp_pis_cofins = sum(r.lp_consumo - r.lp_valor_iss for r in resultados)
    lp_iss = sum(r.lp_valor_iss for r in resultados)
    lp_enc = sum(r.lp_encargos for r in resultados)
    lp_total = sum(r.total_lp for r in resultados)
    
    lr_fed = sum(r.lr_federal for r in resultados)
    lr_pis_cofins = sum(r.lr_consumo - r.lr_valor_iss for r in resultados)
    lr_iss = sum(r.lr_valor_iss for r in resultados)
    lr_enc = sum(r.lr_encargos for r in resultados)
    lr_total = sum(r.total_lr for r in resultados)

    def pct(valor):
        return f"{(valor / tot_fat)*100:.2f}%"

    with tab_efetiva:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Simples Nacional**")
            st.markdown(f"- IRPJ: {formata_reais(sn_irpj)} ({pct(sn_irpj)})")
            st.markdown(f"- CSLL: {formata_reais(sn_csll)} ({pct(sn_csll)})")
            st.markdown(f"- COFINS: {formata_reais(sn_cofins)} ({pct(sn_cofins)})")
            st.markdown(f"- PIS: {formata_reais(sn_pis)} ({pct(sn_pis)})")
            st.markdown(f"- ISS: {formata_reais(sn_iss)} ({pct(sn_iss)})")
            st.markdown(f"- CPP (DAS): {formata_reais(sn_cpp)} ({pct(sn_cpp)})")
            st.markdown(f"- INSS Extra: {formata_reais(sn_extra)} ({pct(sn_extra)})")
            st.markdown(f"**Total: {formata_reais(sn_total)} ({pct(sn_total)})**")
            
        with c2:
            st.markdown("**Lucro Presumido**")
            st.markdown(f"- IRPJ + CSLL: {formata_reais(lp_fed)} ({pct(lp_fed)})")
            st.markdown(f"- PIS/COFINS: {formata_reais(lp_pis_cofins)} ({pct(lp_pis_cofins)})")
            st.markdown(f"- ISS: {formata_reais(lp_iss)} ({pct(lp_iss)})")
            st.markdown(f"- INSS Patronal: {formata_reais(lp_enc)} ({pct(lp_enc)})")
            st.markdown(f"**Total: {formata_reais(lp_total)} ({pct(lp_total)})**")
            
        with c3:
            st.markdown("**Lucro Real**")
            st.markdown(f"- IRPJ + CSLL: {formata_reais(lr_fed)} ({pct(lr_fed)})")
            st.markdown(f"- PIS/COFINS Liq.: {formata_reais(lr_pis_cofins)} ({pct(lr_pis_cofins)})")
            st.markdown(f"- ISS: {formata_reais(lr_iss)} ({pct(lr_iss)})")
            st.markdown(f"- INSS Patronal: {formata_reais(lr_enc)} ({pct(lr_enc)})")
            st.markdown(f"**Total: {formata_reais(lr_total)} ({pct(lr_total)})**")

    with tab_nominal:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Simples Nacional**")
            st.info("No Simples Nacional as alíquotas variam conforme a faixa. Verifique o Excel para ver o detalhamento mês a mês.")
            st.markdown(f"**Total Pago: {formata_reais(sn_total)}**")
            
        with c2:
            st.markdown("**Lucro Presumido**")
            st.markdown(f"- IRPJ (15%) + CSLL (9%): {formata_reais(lp_fed)}")
            st.markdown(f"- PIS (0.65%) / COFINS (3%): {formata_reais(lp_pis_cofins)}")
            st.markdown(f"- ISS ({config.aliquota_issqn*100:.2f}%): {formata_reais(lp_iss)}")
            st.markdown(f"- INSS Patronal: {formata_reais(lp_enc)}")
            st.markdown(f"**Total: {formata_reais(lp_total)}**")
            
        with c3:
            st.markdown("**Lucro Real**")
            st.markdown(f"- IRPJ (15%) + CSLL (9%): {formata_reais(lr_fed)}")
            st.markdown(f"- PIS (1.65%) / COFINS (7.6%): {formata_reais(lr_pis_cofins)}")
            st.markdown(f"- ISS ({config.aliquota_issqn*100:.2f}%): {formata_reais(lr_iss)}")
            st.markdown(f"- INSS Patronal: {formata_reais(lr_enc)}")
            st.markdown(f"**Total: {formata_reais(lr_total)}**")

def exibir_resultados(resultados):
    total_sn_fed = sum(r.sn_federal for r in resultados)
    total_sn_con = sum(r.sn_consumo for r in resultados)
    total_sn_enc = sum(r.sn_encargos for r in resultados)
    total_sn = sum(r.total_sn for r in resultados)
    
    total_lp_fed = sum(r.lp_federal for r in resultados)
    total_lp_con = sum(r.lp_consumo for r in resultados)
    total_lp_enc = sum(r.lp_encargos for r in resultados)
    total_lp = sum(r.total_lp for r in resultados)
    
    total_lr_fed = sum(r.lr_federal for r in resultados)
    total_lr_con = sum(r.lr_consumo for r in resultados)
    total_lr_enc = sum(r.lr_encargos for r in resultados)
    total_lr = sum(r.total_lr for r in resultados)
    
    totais = {"Simples Nacional": total_sn, "Lucro Presumido": total_lp, "Lucro Real": total_lr}
    vencedor = min(totais, key=totais.get)
    
    st.divider()
    st.header(f"🏆 Melhor Regime: :green[{vencedor}]")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Simples Nacional", formata_reais(total_sn), delta="Vencedor!" if vencedor=="Simples Nacional" else None, delta_color="normal" if vencedor=="Simples Nacional" else "off")
    col2.metric("Lucro Presumido", formata_reais(total_lp), delta="Vencedor!" if vencedor=="Lucro Presumido" else None, delta_color="normal" if vencedor=="Lucro Presumido" else "off")
    col3.metric("Lucro Real", formata_reais(total_lr), delta="Vencedor!" if vencedor=="Lucro Real" else None, delta_color="normal" if vencedor=="Lucro Real" else "off")
    
    st.subheader("Composição dos Custos Tributários")
    dados_grafico = [
        {"Regime": "Simples Nacional", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_sn_fed},
        {"Regime": "Simples Nacional", "Categoria": "Impostos s/ Consumo (PIS/COFINS/ISS/DAS)", "Valor": total_sn_con},
        {"Regime": "Simples Nacional", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_sn_enc},
        {"Regime": "Lucro Presumido", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_lp_fed},
        {"Regime": "Lucro Presumido", "Categoria": "Impostos s/ Consumo (PIS/COFINS/ISS/DAS)", "Valor": total_lp_con},
        {"Regime": "Lucro Presumido", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_lp_enc},
        {"Regime": "Lucro Real", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_lr_fed},
        {"Regime": "Lucro Real", "Categoria": "Impostos s/ Consumo (PIS/COFINS/ISS/DAS)", "Valor": total_lr_con},
        {"Regime": "Lucro Real", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_lr_enc},
    ]
    df_grafico = pd.DataFrame(dados_grafico)
    fig = px.bar(df_grafico, x="Regime", y="Valor", color="Categoria", title="Divisão da Carga Tributária", text_auto=".2s")
    fig.update_layout(barmode='stack', yaxis_title="Custo (R$)")
    st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    renderizar_detalhes_tributos(resultados)

# ==========================================
# ABA: PROJEÇÃO 12 MESES
# ==========================================
with tab_projecao:
    st.subheader("📝 Preencha a Projeção (12 Meses)")
    
    col_proj1, col_proj2 = st.columns([2, 1])
    with col_proj1:
        st.markdown("Se você importou o PGDAS ou preencheu o histórico, pode usar os valores médios para projetar os próximos 12 meses automaticamente.")
    with col_proj2:
        taxa_crescimento = st.number_input("Taxa de Crescimento Esperada (%)", value=0.0, step=1.0)
        
    if st.button("Aplicar Projeção Automática", use_container_width=True):
        media_fat = (rbt12_inicial / 12) * (1 + taxa_crescimento/100) if rbt12_inicial > 0 else 0.0
        media_folha = (folha12m_inicial / 12) * (1 + taxa_crescimento/100) if folha12m_inicial > 0 else 0.0
        st.session_state["proj_fat"] = [media_fat] * 12
        st.session_state["proj_folha"] = [media_folha] * 12
        st.rerun()
        
    meses = [f"Mês {i}" for i in range(1, 13)]
    df_initial = pd.DataFrame({
        "Mês": meses,
        "Faturamento Bruto": st.session_state.get("proj_fat", [0.0] * 12),
        "Folha de Pagamento": st.session_state.get("proj_folha", [0.0] * 12),
        "Despesas Dedutíveis (LR)": [0.0] * 12,
        "Compras c/ Crédito PIS/COFINS": [0.0] * 12
    })
    
    edited_df = st.data_editor(
        df_initial, 
        use_container_width=True,
        hide_index=True,
        column_config={
            "Faturamento Bruto": st.column_config.NumberColumn(format="R$ %.2f"),
            "Folha de Pagamento": st.column_config.NumberColumn(format="R$ %.2f"),
            "Despesas Dedutíveis (LR)": st.column_config.NumberColumn(format="R$ %.2f"),
            "Compras c/ Crédito PIS/COFINS": st.column_config.NumberColumn(format="R$ %.2f")
        }
    )
    
    if st.button("🚀 Executar/Salvar Simulação 12 Meses", type="primary", use_container_width=True, key="btn_12m"):
        dados_input = []
        for idx, row in edited_df.iterrows():
            dados_input.append(DadosMes(
                mes=idx + 1,
                faturamento=float(row["Faturamento Bruto"]),
                folha=float(row["Folha de Pagamento"]),
                despesas_dedutiveis=float(row["Despesas Dedutíveis (LR)"]),
                compras_credito=float(row["Compras c/ Crédito PIS/COFINS"])
            ))
        resultados = simular_12_meses(dados_input, config, rbt12_inicial, folha12m_inicial)
        st.session_state['resultados_12m'] = resultados
        st.session_state['dados_input_12m'] = dados_input
        
    if 'resultados_12m' in st.session_state:
        resultados = st.session_state['resultados_12m']
        exibir_resultados(resultados)
        
        st.divider()
        renderizar_impacto_folha(resultados, config)
        
        st.divider()
        excel_data = gerar_excel(resultados, st.session_state['dados_input_12m'])
        st.download_button(
            label="📥 Baixar Excel Detalhado (12 Meses)",
            data=excel_data,
            file_name="simulacao_tributaria_12m.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key="dl_12m"
        )
        
        with st.expander("📂 Histórico de Simulações Salvas"):
            historico = listar_simulacoes()
            if historico:
                df_hist = pd.DataFrame(historico, columns=["ID", "Data", "Vencedor", "Custo SN", "Custo LP", "Custo LR"])
                for col in ["Custo SN", "Custo LP", "Custo LR"]:
                    df_hist[col] = df_hist[col].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma simulação salva ainda.")

# ==========================================
# ABA: SIMULAÇÃO MENSAL
# ==========================================
with tab_mensal:
    st.subheader("📝 Preencha os dados de 1 Mês")
    
    col_f, col_fp = st.columns(2)
    with col_f:
        faturamento_m = st.number_input("Faturamento Bruto (Mês)", value=0.0, step=1000.0, key="fat_m")
    with col_fp:
        folha_m = st.number_input("Folha de Pagamento (Mês)", value=0.0, step=1000.0, key="folha_m")
        
    col_d, col_c = st.columns(2)
    with col_d:
        despesas_m = st.number_input("Despesas Dedutíveis LR (Mês)", value=0.0, step=1000.0, key="desp_m")
    with col_c:
        compras_m = st.number_input("Compras c/ Crédito PIS/COFINS (Mês)", value=0.0, step=1000.0, key="comp_m")
        
    if st.button("⚡ Executar Simulação Mensal", type="primary", use_container_width=True, key="btn_1m"):
        dados_input_mensal = [DadosMes(
            mes=1,
            faturamento=faturamento_m,
            folha=folha_m,
            despesas_dedutiveis=despesas_m,
            compras_credito=compras_m
        )]
        
        resultados_m = simular_12_meses(dados_input_mensal, config, rbt12_inicial, folha12m_inicial)
        st.session_state['resultados_1m'] = resultados_m
        
    if 'resultados_1m' in st.session_state:
        resultados_m = st.session_state['resultados_1m']
        exibir_resultados(resultados_m)
        
        st.divider()
        renderizar_impacto_folha(resultados_m, config)

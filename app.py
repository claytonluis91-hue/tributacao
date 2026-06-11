import streamlit as st
import pandas as pd
import plotly.express as px
import io
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
    
    st.subheader("Lucro Presumido")
    presuncao_irpj = st.number_input("Presunção IRPJ (%)", value=32.0, step=1.0) / 100
    presuncao_csll = st.number_input("Presunção CSLL (%)", value=32.0, step=1.0) / 100

config = ConfigTributaria(
    aliquota_rat=aliquota_rat,
    fap=fap,
    aliquota_terceiros=aliquota_terceiros,
    is_anexo_iv=is_anexo_iv,
    fator_r_sujeito=fator_r_sujeito,
    presuncao_irpj=presuncao_irpj,
    presuncao_csll=presuncao_csll
)

# ---------------------------------------------------------
# INPUTS NA TELA PRINCIPAL
# ---------------------------------------------------------
col_rbt, col_folha = st.columns(2)
with col_rbt:
    rbt12_inicial = st.number_input("RBT12 Acumulado (Anterior) - Deixe 0 se nova", value=0.0, step=10000.0)
with col_folha:
    folha12m_inicial = st.number_input("Folha 12M (Anterior) - Deixe 0 se nova", value=0.0, step=10000.0)

st.subheader("📝 Preencha a Projeção (12 Meses)")

meses = [f"Mês {i}" for i in range(1, 13)]
df_initial = pd.DataFrame({
    "Mês": meses,
    "Faturamento Bruto": [0.0] * 12,
    "Folha de Pagamento": [0.0] * 12,
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

def gerar_excel(resultados, dados_input):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Tabela Simples Nacional
        sn_data = []
        for r in resultados:
            sn_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "RBT12 Calculado": r.sn_rbt12,
                "Fator R": r.sn_fator_r,
                "Alíquota Efetiva": r.sn_aliquota_efetiva,
                "Federal (DAS)": r.sn_federal,
                "Consumo (DAS)": r.sn_consumo,
                "INSS Patronal": r.sn_encargos,
                "Total Mês": r.total_sn
            })
        pd.DataFrame(sn_data).to_excel(writer, sheet_name="Simples Nacional", index=False)

        # Tabela Lucro Presumido
        lp_data = []
        for r in resultados:
            lp_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "Base IRPJ": r.lp_base_irpj,
                "IRPJ/CSLL Normal": r.lp_irpj_csll_normal,
                "Adicional IRPJ (Trimestre)": r.lp_adicional_irpj,
                "PIS/COFINS (Cumulativo)": r.lp_consumo,
                "INSS Patronal": r.lp_encargos,
                "Total Mês": r.total_lp
            })
        pd.DataFrame(lp_data).to_excel(writer, sheet_name="Lucro Presumido", index=False)

        # Tabela Lucro Real
        lr_data = []
        for r in resultados:
            lr_data.append({
                "Mês": r.mes,
                "Faturamento": r.faturamento,
                "LAIR": r.lr_lair,
                "IRPJ/CSLL Normal": r.lr_irpj_csll_normal,
                "Adicional IRPJ (>20k)": r.lr_adicional_irpj,
                "PIS/COFINS (Não Cumulativo)": r.lr_consumo,
                "INSS Patronal": r.lr_encargos,
                "Total Mês": r.total_lr
            })
        pd.DataFrame(lr_data).to_excel(writer, sheet_name="Lucro Real", index=False)

    return output.getvalue()

if st.button("🚀 Executar/Salvar Simulação", type="primary", use_container_width=True):
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
    
    # State Management para o Download Button funcionar sem recarregar e perder a simulação
    st.session_state['resultados'] = resultados
    st.session_state['dados_input'] = dados_input
    st.session_state['detalhes_input'] = edited_df.to_dict('records')
    
if 'resultados' in st.session_state:
    resultados = st.session_state['resultados']
    
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
    
    totais = {
        "Simples Nacional": total_sn,
        "Lucro Presumido": total_lp,
        "Lucro Real": total_lr
    }
    vencedor = min(totais, key=totais.get)
    
    # Só salva no banco de dados na primeira vez que clicar no botão (opcional colocar flag)
    # Mas pra simplificar, ele salva sempre que o botão principal roda. 
    # Como st.session_state persiste a renderização abaixo, o botão de download não re-salva.
    
    st.divider()
    col_vencedor, col_download = st.columns([0.7, 0.3])
    
    with col_vencedor:
        st.header(f"🏆 Melhor Regime: :green[{vencedor}]")
        
    with col_download:
        excel_data = gerar_excel(resultados, st.session_state['dados_input'])
        st.download_button(
            label="📥 Baixar Excel Detalhado",
            data=excel_data,
            file_name="simulacao_tributaria.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )
    
    col1, col2, col3 = st.columns(3)
    
    def formata_reais(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
    col1.metric("Simples Nacional", formata_reais(total_sn), delta=f"Vencedor!" if vencedor=="Simples Nacional" else None, delta_color="normal" if vencedor=="Simples Nacional" else "off")
    col2.metric("Lucro Presumido", formata_reais(total_lp), delta=f"Vencedor!" if vencedor=="Lucro Presumido" else None, delta_color="normal" if vencedor=="Lucro Presumido" else "off")
    col3.metric("Lucro Real", formata_reais(total_lr), delta=f"Vencedor!" if vencedor=="Lucro Real" else None, delta_color="normal" if vencedor=="Lucro Real" else "off")
    
    st.subheader("Composição dos Custos Tributários")
    
    dados_grafico = [
        {"Regime": "Simples Nacional", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_sn_fed},
        {"Regime": "Simples Nacional", "Categoria": "Impostos s/ Consumo (PIS/COFINS/DAS)", "Valor": total_sn_con},
        {"Regime": "Simples Nacional", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_sn_enc},
        
        {"Regime": "Lucro Presumido", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_lp_fed},
        {"Regime": "Lucro Presumido", "Categoria": "Impostos s/ Consumo (PIS/COFINS/DAS)", "Valor": total_lp_con},
        {"Regime": "Lucro Presumido", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_lp_enc},
        
        {"Regime": "Lucro Real", "Categoria": "Impostos Federais (IRPJ/CSLL)", "Valor": total_lr_fed},
        {"Regime": "Lucro Real", "Categoria": "Impostos s/ Consumo (PIS/COFINS/DAS)", "Valor": total_lr_con},
        {"Regime": "Lucro Real", "Categoria": "Encargos s/ Folha (INSS)", "Valor": total_lr_enc},
    ]
    
    df_grafico = pd.DataFrame(dados_grafico)
    
    fig = px.bar(
        df_grafico, 
        x="Regime", 
        y="Valor", 
        color="Categoria", 
        title="Divisão da Carga Tributária Anual",
        text_auto=".2s"
    )
    fig.update_layout(barmode='stack', yaxis_title="Custo (R$)")
    st.plotly_chart(fig, use_container_width=True)

st.divider()
with st.expander("📂 Histórico de Simulações Salvas"):
    historico = listar_simulacoes()
    if historico:
        df_hist = pd.DataFrame(historico, columns=["ID", "Data", "Vencedor", "Custo SN", "Custo LP", "Custo LR"])
        for col in ["Custo SN", "Custo LP", "Custo LR"]:
            df_hist[col] = df_hist[col].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma simulação salva ainda.")

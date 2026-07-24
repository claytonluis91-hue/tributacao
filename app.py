from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db import init_db, listar_simulacoes, salvar_simulacao
from engine_tributario import ConfigTributaria, DadosMes, simular_12_meses
from excel_export import gerar_excel
from pgdas_parser import extrair_dados_pgdas


st.set_page_config(
    page_title="TributaSim | Planejamento tributário",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: #f8fafc; }
      [data-testid="stSidebar"] { background: #0f172a; }
      [data-testid="stSidebar"] * { color: #f8fafc; }
      [data-testid="stSidebar"] input {
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        caret-color: #0f172a;
      }
      [data-testid="stSidebar"] [data-baseweb="input"] button,
      [data-testid="stSidebar"] [data-baseweb="input"] button * {
        color: #475569 !important;
        fill: #475569 !important;
      }
      [data-testid="stSidebar"] [data-testid="stExpander"] summary,
      [data-testid="stSidebar"] [data-testid="stExpander"] summary * {
        color: #0f172a !important;
        fill: #0f172a !important;
      }
      .hero {
        padding: 1.6rem 1.8rem; border-radius: 18px;
        background: linear-gradient(125deg, #0f172a 0%, #0f766e 100%);
        color: white; margin-bottom: 1rem; box-shadow: 0 12px 32px #0f172a20;
      }
      .hero h1 { margin: 0; font-size: 2rem; }
      .hero p { margin: .45rem 0 0; color: #ccfbf1; }
      .section-note {
        border-left: 4px solid #0f766e; background: white; padding: .8rem 1rem;
        border-radius: 8px; color: #334155; margin: .5rem 0 1rem;
      }
      div[data-testid="stMetric"] {
        background: white; border: 1px solid #e2e8f0; padding: 1rem;
        border-radius: 14px; box-shadow: 0 4px 16px #0f172a0d;
      }
      .stTabs [data-baseweb="tab-list"] { gap: .5rem; }
      .stTabs [data-baseweb="tab"] {
        background: white; border-radius: 10px 10px 0 0; padding: .6rem 1rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()


def reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def periodo(valor: str) -> pd.Period:
    return pd.to_datetime(f"01/{valor}", dayfirst=True).to_period("M")


def historico_vazio() -> list[dict]:
    fim = pd.Period(datetime.now(), freq="M") - 1
    meses = pd.period_range(end=fim, periods=12, freq="M")
    return [
        {
            "Competência": item.strftime("%m/%Y"),
            "Faturamento": 0.0,
            "Folha": 0.0,
            "Origem": "Entrada manual",
        }
        for item in meses
    ]


def gerar_projecao(
    historico: pd.DataFrame,
    metodo: str,
    crescimento: float,
    despesas_pct: float,
    creditos_pct: float,
) -> pd.DataFrame:
    hist = historico.copy().tail(12)
    receitas = hist["Faturamento"].astype(float).tolist()
    folhas = hist["Folha"].astype(float).tolist()
    ultima_competencia = periodo(str(hist.iloc[-1]["Competência"]))
    futuras = [ultima_competencia + i for i in range(1, 13)]

    if metodo.startswith("Sazonalidade"):
        proj_receita = receitas
        proj_folha = folhas
    elif metodo.startswith("Média dos últimos 3"):
        proj_receita = [sum(receitas[-3:]) / 3] * 12
        proj_folha = [sum(folhas[-3:]) / 3] * 12
    else:
        proj_receita = [sum(receitas) / 12] * 12
        proj_folha = [sum(folhas) / 12] * 12

    # A taxa anual é aplicada ao mês equivalente do histórico; a tabela fica
    # totalmente editável antes do cálculo.
    fator = 1 + crescimento
    proj_receita = [max(valor * fator, 0) for valor in proj_receita]
    proj_folha = [max(valor * fator, 0) for valor in proj_folha]
    return pd.DataFrame(
        {
            "Competência": [item.strftime("%m/%Y") for item in futuras],
            "Faturamento": proj_receita,
            "Folha": proj_folha,
            "Despesas dedutíveis (LR)": [valor * despesas_pct for valor in proj_receita],
            "Base de aquisições com crédito": [valor * creditos_pct for valor in proj_receita],
        }
    )


def dataframe_resultados(resultados) -> pd.DataFrame:
    linhas = []
    for r in resultados:
        custos = {
            "Simples Nacional": r.total_sn,
            "Lucro Presumido": r.total_lp,
            "Lucro Real": r.total_lr,
        }
        ordem = sorted(custos.items(), key=lambda item: item[1])
        linhas.append(
            {
                "Competência": r.competencia,
                "Faturamento": r.faturamento,
                "RBT12": r.sn_rbt12,
                "Fator R": r.sn_fator_r,
                "Anexo": r.sn_anexo,
                "Alíquota SN": r.sn_aliquota_efetiva,
                "Simples Nacional": r.total_sn,
                "Lucro Presumido": r.total_lp,
                "Lucro Real": r.total_lr,
                "Melhor regime": ordem[0][0],
                "Economia para o 2º": ordem[1][1] - ordem[0][1],
            }
        )
    return pd.DataFrame(linhas)


if "historico" not in st.session_state:
    st.session_state.historico = historico_vazio()
if "projecao" not in st.session_state:
    st.session_state.projecao = None
if "metadados_pgdas" not in st.session_state:
    st.session_state.metadados_pgdas = {}


with st.sidebar:
    st.markdown("## Premissas tributárias")
    st.caption("Parâmetros editáveis usados em todos os cenários.")
    ano_referencia = st.number_input("Ano de referência", 2026, 2032, 2026, 1)
    aliquota_issqn = (
        st.number_input(
            "ISS (%)",
            min_value=0.0,
            max_value=5.0,
            value=2.0,
            step=0.25,
            help="Confirme a alíquota da atividade no município competente.",
        )
        / 100
    )

    with st.expander("Simples Nacional", expanded=True):
        is_anexo_iv = st.checkbox(
            "Atividade no Anexo IV",
            value=False,
            help="No Anexo IV a CPP patronal não integra o DAS.",
        )
        fator_r_sujeito = st.checkbox(
            "Atividade sujeita ao Fator R",
            value=True,
            disabled=is_anexo_iv,
            help="Anexo III quando o Fator R é igual ou superior a 28%; Anexo V abaixo de 28%.",
        )

    with st.expander("Folha e encargos"):
        aliquota_rat = st.number_input("RAT (%)", 0.0, 3.0, 2.0, 0.5) / 100
        fap = st.number_input("FAP", 0.5, 2.0, 1.0, 0.1)
        aliquota_terceiros = st.number_input("Terceiros (%)", 0.0, 10.0, 5.8, 0.1) / 100
        st.caption(
            f"Encargo patronal simulado: {(0.20 + aliquota_rat * fap + aliquota_terceiros):.2%}"
        )

    with st.expander("Lucro Presumido"):
        presuncao_irpj = st.number_input("Presunção IRPJ (%)", 0.0, 100.0, 32.0, 1.0) / 100
        presuncao_csll = st.number_input("Presunção CSLL (%)", 0.0, 100.0, 32.0, 1.0) / 100

    st.warning(
        "2026 é ano-teste de IBS/CBS. O modelo mantém PIS/Cofins/ISS na carga e considera "
        "a dispensa do recolhimento-teste condicionada às obrigações acessórias."
    )

config = ConfigTributaria(
    aliquota_rat=aliquota_rat,
    fap=fap,
    aliquota_terceiros=aliquota_terceiros,
    is_anexo_iv=is_anexo_iv,
    fator_r_sujeito=fator_r_sujeito,
    presuncao_irpj=presuncao_irpj,
    presuncao_csll=presuncao_csll,
    aliquota_issqn=aliquota_issqn,
    ano_referencia=int(ano_referencia),
)

st.markdown(
    """
    <div class="hero">
      <h1>TributaSim</h1>
      <p>Planejamento tributário com histórico real, projeção mensal e memória de cálculo.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_historico, tab_projecao, tab_resultado = st.tabs(
    ["1 · Histórico", "2 · Projeção", "3 · Resultado e Excel"]
)

with tab_historico:
    st.subheader("Importe o PGDAS-D ou informe os últimos 12 meses")
    st.markdown(
        '<div class="section-note">O histórico mensal é essencial: cada projeção retira o mês '
        "mais antigo e acrescenta o novo faturamento para recalcular RBT12, FS12 e Fator R.</div>",
        unsafe_allow_html=True,
    )
    arquivo = st.file_uploader("Extrato do PGDAS-D (PDF)", type=["pdf"])
    if arquivo is not None:
        chave = f"{arquivo.name}:{arquivo.size}"
        if st.session_state.get("arquivo_processado") != chave:
            try:
                extraido = extrair_dados_pgdas(arquivo.getvalue())
                if len(extraido["historico"]) == 12:
                    st.session_state.historico = extraido["historico"]
                    st.session_state.metadados_pgdas = {
                        "arquivo_pgdas": arquivo.name,
                        "pa": extraido["pa"],
                        "rbt12_declarado": extraido["rbt12"],
                        "fator_r_declarado": extraido["fator_r"],
                    }
                    st.session_state.arquivo_processado = chave
                    st.session_state.projecao = None
                    st.success(
                        f"PGDAS importado: PA {extraido['pa']} • RPA {reais(extraido['rpa'])} • "
                        f"RBT12 declarado {reais(extraido['rbt12'])}."
                    )
                else:
                    st.error("O PDF não forneceu 12 competências utilizáveis. Complete a tabela manualmente.")
            except Exception as exc:
                st.error(f"Não foi possível ler o PGDAS-D: {exc}")

    df_hist = pd.DataFrame(st.session_state.historico)
    historico_editado = st.data_editor(
        df_hist,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Competência": st.column_config.TextColumn(width="small"),
            "Faturamento": st.column_config.NumberColumn(format="R$ %.2f", min_value=0.0),
            "Folha": st.column_config.NumberColumn(format="R$ %.2f", min_value=0.0),
            "Origem": st.column_config.TextColumn(disabled=True),
        },
        key="editor_historico",
    )
    st.session_state.historico = historico_editado.to_dict("records")

    c1, c2, c3, c4 = st.columns(4)
    rbt_hist = float(historico_editado["Faturamento"].sum())
    folha_hist = float(historico_editado["Folha"].sum())
    c1.metric("Receita dos 12 meses", reais(rbt_hist))
    c2.metric("Folha dos 12 meses", reais(folha_hist))
    c3.metric("Fator R histórico", f"{folha_hist / rbt_hist:.2%}" if rbt_hist else "—")
    c4.metric("Média mensal", reais(rbt_hist / 12))
    if any("estimada" in str(v).lower() for v in historico_editado["Origem"]):
        st.info("A folha do período de apuração do PDF foi estimada pela média. Revise-a na tabela.")

with tab_projecao:
    st.subheader("Construa o cenário dos próximos 12 meses")
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        metodo = st.selectbox(
            "Método de projeção",
            [
                "Sazonalidade (mesmo mês do ano anterior)",
                "Média dos últimos 3 meses",
                "Média dos últimos 12 meses",
            ],
        )
    with c2:
        crescimento = st.number_input("Crescimento anual (%)", -50.0, 200.0, 5.0, 1.0) / 100
    with c3:
        despesas_pct = st.number_input("Despesas LR (% receita)", 0.0, 100.0, 55.0, 1.0) / 100
    with c4:
        creditos_pct = st.number_input("Base créditos (% receita)", 0.0, 100.0, 10.0, 1.0) / 100

    if st.button("Aplicar projeção a partir do histórico", type="secondary", use_container_width=True):
        try:
            st.session_state.projecao = gerar_projecao(
                pd.DataFrame(st.session_state.historico),
                metodo,
                crescimento,
                despesas_pct,
                creditos_pct,
            )
        except Exception as exc:
            st.error(f"Revise as competências e valores do histórico: {exc}")

    if st.session_state.projecao is None:
        st.info("Aplique um método de projeção para preencher os próximos 12 meses.")
    else:
        projecao_editada = st.data_editor(
            st.session_state.projecao,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Competência": st.column_config.TextColumn(width="small"),
                "Faturamento": st.column_config.NumberColumn(format="R$ %.2f", min_value=0.0),
                "Folha": st.column_config.NumberColumn(format="R$ %.2f", min_value=0.0),
                "Despesas dedutíveis (LR)": st.column_config.NumberColumn(
                    format="R$ %.2f", min_value=0.0
                ),
                "Base de aquisições com crédito": st.column_config.NumberColumn(
                    format="R$ %.2f", min_value=0.0
                ),
            },
            key="editor_projecao",
        )
        st.session_state.projecao = projecao_editada
        st.caption(
            "Despesas e créditos são premissas críticas para o Lucro Real. Ajuste os valores com "
            "base na contabilidade e na documentação fiscal."
        )
        if st.button("Simular e salvar cenário", type="primary", use_container_width=True):
            dados = [
                DadosMes(
                    mes=i + 1,
                    competencia=str(row["Competência"]),
                    faturamento=float(row["Faturamento"]),
                    folha=float(row["Folha"]),
                    despesas_dedutiveis=float(row["Despesas dedutíveis (LR)"]),
                    compras_credito=float(row["Base de aquisições com crédito"]),
                )
                for i, (_, row) in enumerate(projecao_editada.iterrows())
            ]
            hist_df = pd.DataFrame(st.session_state.historico).tail(12)
            resultados = simular_12_meses(
                dados,
                config,
                rbt12_inicial=float(hist_df["Faturamento"].sum()),
                folha12m_inicial=float(hist_df["Folha"].sum()),
                historico_faturamento=hist_df["Faturamento"].astype(float).tolist(),
                historico_folha=hist_df["Folha"].astype(float).tolist(),
            )
            st.session_state.resultados = resultados
            st.session_state.dados_simulados = dados
            st.session_state.config_simulada = config
            totais_salvar = {
                "Simples Nacional": sum(r.total_sn for r in resultados),
                "Lucro Presumido": sum(r.total_lp for r in resultados),
                "Lucro Real": sum(r.total_lr for r in resultados),
            }
            vencedor_salvar = min(totais_salvar, key=totais_salvar.get)
            salvar_simulacao(
                vencedor_salvar,
                totais_salvar["Simples Nacional"],
                totais_salvar["Lucro Presumido"],
                totais_salvar["Lucro Real"],
                {"competencias": [r.competencia for r in resultados]},
            )
            st.success("Cenário calculado e registrado. Abra a aba “Resultado e Excel”.")

with tab_resultado:
    if "resultados" not in st.session_state:
        st.info("Calcule um cenário na aba de projeção para visualizar a comparação.")
    else:
        resultados = st.session_state.resultados
        df_result = dataframe_resultados(resultados)
        totais = {
            "Simples Nacional": float(df_result["Simples Nacional"].sum()),
            "Lucro Presumido": float(df_result["Lucro Presumido"].sum()),
            "Lucro Real": float(df_result["Lucro Real"].sum()),
        }
        ranking = sorted(totais.items(), key=lambda item: item[1])
        faturamento_total = float(df_result["Faturamento"].sum())
        economia = ranking[1][1] - ranking[0][1]

        st.subheader(f"Melhor resultado projetado: {ranking[0][0]}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Simples Nacional", reais(totais["Simples Nacional"]))
        c2.metric("Lucro Presumido", reais(totais["Lucro Presumido"]))
        c3.metric("Lucro Real", reais(totais["Lucro Real"]))
        c4.metric("Economia vs. 2º", reais(economia))

        grafico = df_result.melt(
            id_vars=["Competência"],
            value_vars=["Simples Nacional", "Lucro Presumido", "Lucro Real"],
            var_name="Regime",
            value_name="Carga tributária",
        )
        fig = px.line(
            grafico,
            x="Competência",
            y="Carga tributária",
            color="Regime",
            markers=True,
            color_discrete_map={
                "Simples Nacional": "#0f766e",
                "Lucro Presumido": "#2563eb",
                "Lucro Real": "#f59e0b",
            },
        )
        fig.update_layout(
            title="Carga tributária mês a mês",
            yaxis_tickprefix="R$ ",
            hovermode="x unified",
            legend_title="",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,1)",
        )
        st.plotly_chart(fig, use_container_width=True)

        col_esq, col_dir = st.columns(2)
        with col_esq:
            fig_r = go.Figure()
            fig_r.add_trace(
                go.Bar(
                    x=df_result["Competência"],
                    y=df_result["Fator R"],
                    marker_color=[
                        "#0f766e" if valor >= 0.28 else "#dc2626"
                        for valor in df_result["Fator R"]
                    ],
                    name="Fator R",
                )
            )
            fig_r.add_hline(y=0.28, line_dash="dash", line_color="#0f172a")
            fig_r.update_layout(
                title="Fator R e limite de 28%",
                yaxis_tickformat=".0%",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="white",
            )
            st.plotly_chart(fig_r, use_container_width=True)
        with col_dir:
            aliquotas = pd.DataFrame(
                {
                    "Regime": list(totais),
                    "Alíquota efetiva": [
                        valor / faturamento_total if faturamento_total else 0
                        for valor in totais.values()
                    ],
                }
            )
            fig_a = px.bar(
                aliquotas,
                x="Regime",
                y="Alíquota efetiva",
                color="Regime",
                text_auto=".2%",
                color_discrete_sequence=["#0f766e", "#2563eb", "#f59e0b"],
            )
            fig_a.update_layout(
                title="Alíquota efetiva no horizonte",
                showlegend=False,
                yaxis_tickformat=".0%",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="white",
            )
            st.plotly_chart(fig_a, use_container_width=True)

        st.markdown("#### Apuração comparativa por competência")
        st.dataframe(
            df_result,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Faturamento": st.column_config.NumberColumn(format="R$ %.2f"),
                "RBT12": st.column_config.NumberColumn(format="R$ %.2f"),
                "Fator R": st.column_config.NumberColumn(format="%.2f%%"),
                "Alíquota SN": st.column_config.NumberColumn(format="%.2f%%"),
                "Simples Nacional": st.column_config.NumberColumn(format="R$ %.2f"),
                "Lucro Presumido": st.column_config.NumberColumn(format="R$ %.2f"),
                "Lucro Real": st.column_config.NumberColumn(format="R$ %.2f"),
                "Economia para o 2º": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

        observacoes = sorted({r.sn_observacao for r in resultados if r.sn_observacao})
        for observacao in observacoes:
            st.warning(observacao)

        excel = gerar_excel(
            resultados,
            st.session_state.dados_simulados,
            st.session_state.config_simulada,
            st.session_state.historico,
            st.session_state.metadados_pgdas,
        )
        st.download_button(
            "Baixar Excel completo e auditável",
            data=excel,
            file_name="simulacao_tributaria_mensal.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

        with st.expander("Histórico de cenários salvos"):
            historico_db = listar_simulacoes()
            if historico_db:
                df_db = pd.DataFrame(
                    historico_db,
                    columns=["ID", "Data", "Regime vencedor", "Simples", "Presumido", "Real"],
                )
                st.dataframe(
                    df_db,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Simples": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Presumido": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Real": st.column_config.NumberColumn(format="R$ %.2f"),
                    },
                )
            else:
                st.caption("Nenhum cenário salvo.")

        with st.expander("Escopo e limitações"):
            st.markdown(
                """
                - Lucro Presumido e Lucro Real são tratados com fechamento trimestral.
                - O adicional do IRPJ é calculado sobre a parcela que excede R$ 20 mil por mês
                  do período e aparece no último mês do trimestre.
                - Para 2026, o acréscimo de 10% nos percentuais de presunção é aplicado à receita
                  trimestral acima de R$ 1,25 milhão, observada a vigência específica da CSLL.
                - Créditos de PIS/Cofins são limitados ao débito no modelo e dependem de
                  elegibilidade/documentação na apuração real.
                - O resultado não substitui parecer contábil ou fiscal.
                """
            )

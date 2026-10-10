"""Site de simulados ISS Curitiba — app Flask para Vercel (serverless).

Roda também localmente:  python api/index.py
Banco: PostgreSQL da VPS (mesmos dados do sync_vps.py). Variáveis de
ambiente necessárias: VPS_PG_HOST, VPS_PG_USER, VPS_PG_PASSWORD,
SITE_PASSWORD (senha de acesso ao site), FLASK_SECRET.
"""

import json
import os
import random
import re
from functools import wraps

import psycopg2
import psycopg2.extras
from flask import (Flask, abort, redirect, render_template, request, session,
                   url_for)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except ImportError:
    pass

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__),
                                                   "..", "templates"))
app.secret_key = os.environ.get("FLASK_SECRET", "dev-inseguro-mude-me")


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
def pg():
    return psycopg2.connect(
        host=os.environ["VPS_PG_HOST"],
        port=int(os.environ.get("VPS_PG_PORT", "5432")),
        dbname=os.environ.get("VPS_PG_DBNAME", "iss_curitiba"),
        user=os.environ["VPS_PG_USER"],
        password=os.environ["VPS_PG_PASSWORD"],
    )


# ---------------------------------------------------------------------------
# Acesso livre (senha removida a pedido do usuário — uso pessoal)
# ---------------------------------------------------------------------------
def exige_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        if request.form.get("senha") == os.environ.get("SITE_PASSWORD"):
            session["autorizado"] = True
            return redirect(request.args.get("proximo") or url_for("inicio"))
        erro = "Senha incorreta."
    return render_template("login.html", erro=erro)


# ---------------------------------------------------------------------------
# Sorteio balanceado por tema (mapa curado código -> regex de disciplina)
# ---------------------------------------------------------------------------
MAPA_MACRO = {
    "1.1": r"portugu",
    "1.2": r"noç(õ|o)es de inform(á|a)tica|^inform(á|a)tica",
    "2.1": r"legisla(ç|c)(ã|a)o (municipal|dos munic)|hist(ó|o)ria e geografia",
    "2.2": r"matem(á|a)tica|racioc|estat(í|i)stica",
    "2.3": (r"banco de dados|arquitetura de (software|computadores)|"
            r"engenharia de (software|dados)|algoritmos|"
            r"redes de computadores|sistemas operacionais|"
            r"seguran(ç|c)a da informa(ç|c)(ã|a)o|analytics|"
            r"aprendizado de m(á|a)quina|intelig(ê|e)ncia artificial|"
            r"processamento de linguagem|ci(ê|e)ncia de dados?|"
            r"big data|computa(ç|c)(ã|a)o em nuvem|linguagem (python|r)|"
            r"lgpd|prote(ç|c)(ã|a)o de dados"),
    "2.4": r"direito constitucional",
    "2.5": r"direito administrativo",
    "2.6": r"direito tribut(á|a)rio|reforma tribut(á|a)ria do consumo",
    "2.7": r"",  # ISSQN: conta por palavra-chave no enunciado
    "2.8": r"",  # idem
    "2.9": r"munic(í|i)pios do estado do paran(á|a)|legisla(ç|c)(ã|a)o municipal",
    "2.10": r"processo administrativo tribut(á|a)rio",
    "2.11": r"reforma tribut(á|a)ria",
    "2.12": r"contabilidade",
    "2.13": r"direito civil|direito empresarial|direito comercial",
    "2.14": r"direito penal tribut(á|a)rio",
    "2.15": r"^economia",
}
KEYWORDS_TEMA = {
    "2.7": r"issqn|\biss\b|imposto sobre servi",
    "2.8": r"iptu|itbi|imposto predial",
}
TRIBUTO_OU_MUNICIPAL = (r"direito tribut|legisla(ç|c)(ã|a)o municipal|"
                        r"munic(í|i)pios do estado do paran")


def _distribuir(n, k):
    if k <= 0:
        return []
    base, resto = divmod(n, k)
    return [base + (1 if i < resto else 0) for i in range(k)]


def _sortear_por_grupo(cur, temas, n, ja_usados):
    """Sorteia n questões cobrindo o máximo de temas do grupo."""
    if n <= 0 or not temas:
        return []
    rnd = random.SystemRandom()
    embaralhados = rnd.sample(list(temas), len(temas))
    cotas = _distribuir(n, len(embaralhados))
    ids = []
    for tema, cota in zip(embaralhados, cotas):
        if cota <= 0 or len(ids) >= n:
            continue
        cod = tema["codigo"]
        regex = MAPA_MACRO.get(cod, "")
        kw = KEYWORDS_TEMA.get(cod, "")
        if not regex and not kw:
            continue
        sql_where = ("fonte = 'fafipa-real' AND gabarito != '' AND ")
        params = []
        conds = []
        if regex:
            conds.append("tema ~* %s")
            params.append(regex)
        if kw:
            conds.append("enunciado ~* %s AND tema ~* %s")
            params += [kw, TRIBUTO_OU_MUNICIPAL]
        sql_where += "(" + " OR ".join(conds) + ")"
        if ja_usados:
            sql_where += " AND id NOT IN %s"
            params.append(tuple(ja_usados))
        params.append(min(cota, n - len(ids)))
        cur.execute(
            f"SELECT id FROM questoes WHERE {sql_where} "
            "ORDER BY RANDOM() LIMIT %s", params)
        novos = [r["id"] for r in cur.fetchall()]
        ids.extend(novos)
        ja_usados.update(novos)
    faltam = n - len(ids)
    if faltam > 0:
        sql = ("SELECT id FROM questoes WHERE (fonte = 'fafipa-real' "
               "OR aprovada = 1) AND gabarito != ''")
        params = []
        if ja_usados:
            sql += " AND id NOT IN %s"
            params.append(tuple(ja_usados))
        params.append(faltam)
        cur.execute(sql + " ORDER BY RANDOM() LIMIT %s", params)
        novos = [r["id"] for r in cur.fetchall()]
        ids.extend(novos)
        ja_usados.update(novos)
    return ids


def montar_simulado(cur, n_questoes, excluir_feitas=False):
    """Estrutura da prova real (edital): 12,5% Português, 12,5% Informática,
    75% Específicos (ex.: 40 questões = 5 + 5 + 30)."""
    cur.execute("SELECT codigo, descricao FROM temas ORDER BY codigo")
    temas = cur.fetchall()
    portugues = [t for t in temas if t["codigo"] == "1.1"]
    informatica = [t for t in temas if t["codigo"] == "1.2"]
    especificos = [t for t in temas if t["codigo"].count(".") == 1
                   and t["codigo"].startswith("2.")]
    n_port = round(n_questoes * 0.125)
    n_info = round(n_questoes * 0.125)
    n_esp = n_questoes - n_port - n_info
    usados = set()
    if excluir_feitas:
        cur.execute("SELECT DISTINCT questao_id FROM respostas")
        usados.update(r["questao_id"] for r in cur.fetchall())
    ids = _sortear_por_grupo(cur, especificos, n_esp, usados)
    ids += _sortear_por_grupo(cur, portugues, n_port, usados)
    ids += _sortear_por_grupo(cur, informatica, n_info, usados)
    if not ids:
        raise RuntimeError(
            "Sem questões disponíveis no banco."
            if not excluir_feitas else
            "Você já respondeu todas as questões do banco com esses filtros. "
            "Desmarque 'não repetir' ou reduza o número de questões.")
    cur.execute(
        "INSERT INTO simulados (data, n_questoes, config_json) "
        "VALUES (NOW(), %s, %s) RETURNING id", (len(ids), json.dumps(
            {"n_questoes": n_questoes,
             "estrutura": "12.5% português + 12.5% informática + 75% específicos"})))
    sid = cur.fetchone()["id"]
    cur.executemany(
        "INSERT INTO respostas (simulado_id, questao_id) VALUES (%s, %s)",
        [(sid, qid) for qid in ids])
    return sid


# ---------------------------------------------------------------------------
# Rotas do simulado
# ---------------------------------------------------------------------------
@app.route("/")
@exige_login
def inicio():
    with pg() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COUNT(*) c FROM questoes WHERE gabarito != ''")
        n_questoes = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM simulados")
        n_simulados = cur.fetchone()["c"]
        cur.execute(
            "SELECT COUNT(DISTINCT questao_id) c FROM respostas "
            "WHERE resposta_marcada IS NOT NULL")
        n_respondidas = cur.fetchone()["c"]
    return render_template("index.html", n_questoes=n_questoes,
                           n_simulados=n_simulados,
                           n_respondidas=n_respondidas)


@app.route("/iniciar", methods=["POST"])
@exige_login
def iniciar():
    n = max(5, min(120, int(request.form.get("n_questoes", 40))))
    excluir = bool(request.form.get("excluir_feitas"))
    try:
        with pg() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sid = montar_simulado(cur, n, excluir_feitas=excluir)
            conn.commit()
    except RuntimeError as e:
        return render_template("erro.html", mensagem=str(e)), 400
    session["simulado_id"] = sid
    session["indice"] = 0
    return redirect(url_for("prova"))


def _questao_atual(cur, sid, indice):
    cur.execute(
        "SELECT q.id, q.tema, q.enunciado, q.alt_a, q.alt_b, q.alt_c, "
        "q.alt_d, q.alt_e, r.resposta_marcada "
        "FROM respostas r JOIN questoes q ON q.id = r.questao_id "
        "WHERE r.simulado_id = %s ORDER BY r.id LIMIT 1 OFFSET %s",
        (sid, indice))
    return cur.fetchone()


@app.route("/prova", methods=["GET", "POST"])
@exige_login
def prova():
    sid = session.get("simulado_id")
    if not sid:
        return redirect(url_for("inicio"))
    with pg() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COUNT(*) c FROM respostas WHERE simulado_id = %s",
                    (sid,))
        total = cur.fetchone()["c"]
        if request.method == "POST":
            acao = request.form.get("acao", "")
            qid = int(request.form.get("questao_id", 0))
            marcada = request.form.get("marcada", "")
            cur.execute(
                "UPDATE respostas SET resposta_marcada = %s "
                "WHERE simulado_id = %s AND questao_id = %s",
                (marcada or None, sid, qid))
            conn.commit()
            if acao == "submeter":
                return redirect(url_for("resultado"))
            session["indice"] = max(0, min(total - 1, session["indice"]
                                           + (1 if acao == "proxima"
                                              else -1)))
            return redirect(url_for("prova"))
        indice = min(session.get("indice", 0), total - 1)
        q = _questao_atual(cur, sid, indice)
        cur.execute(
            "SELECT COUNT(*) c FROM respostas WHERE simulado_id = %s "
            "AND resposta_marcada IS NOT NULL", (sid,))
        respondidas = cur.fetchone()["c"]
    alts = [(letra, q[f"alt_{letra.lower()}"]) for letra in "ABCDE"
            if q[f"alt_{letra.lower()}"].strip()]
    return render_template("prova.html", q=q, indice=indice, total=total,
                           alts=alts, respondidas=respondidas,
                           marcada=q["resposta_marcada"] or "")


@app.route("/resultado")
@exige_login
def resultado():
    sid = session.get("simulado_id")
    if not sid:
        return redirect(url_for("inicio"))
    with pg() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "UPDATE respostas SET correta = CASE WHEN resposta_marcada = "
            "(SELECT gabarito FROM questoes WHERE id = questao_id) THEN 1 "
            "ELSE 0 END WHERE simulado_id = %s AND resposta_marcada "
            "IS NOT NULL", (sid,))
        cur.execute(
            "SELECT q.id, q.tema, q.enunciado, q.gabarito, q.justificativa, "
            "r.resposta_marcada, r.correta FROM respostas r "
            "JOIN questoes q ON q.id = r.questao_id "
            "WHERE r.simulado_id = %s ORDER BY r.id", (sid,))
        questoes = cur.fetchall()
        conn.commit()
    acertos = sum(1 for q in questoes if q["correta"])
    total = len(questoes)
    por_tema = {}
    for q in questoes:
        d = por_tema.setdefault(q["tema"] or "(sem tema)",
                                {"acertos": 0, "total": 0})
        d["total"] += 1
        d["acertos"] += 1 if q["correta"] else 0
    return render_template("resultado.html", nota=round(100 * acertos / total,
                                                        1) if total else 0,
                           acertos=acertos, total=total,
                           por_tema=por_tema, questoes=questoes)


def _corrigir(cur, sid):
    cur.execute(
        "UPDATE respostas SET correta = CASE WHEN resposta_marcada = "
        "(SELECT gabarito FROM questoes WHERE id = questao_id) THEN 1 "
        "ELSE 0 END WHERE simulado_id = %s AND resposta_marcada "
        "IS NOT NULL", (sid,))


@app.route("/historico")
@exige_login
def historico():
    with pg() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM simulados ORDER BY id DESC")
        sids = [r["id"] for r in cur.fetchall()]
        simulados = []
        for sid in sids:
            _corrigir(cur, sid)
            cur.execute(
                "SELECT s.id, s.data, s.n_questoes, COUNT(r.id) respondidas, "
                "SUM(CASE WHEN r.correta = 1 THEN 1 ELSE 0 END) acertos "
                "FROM simulados s JOIN respostas r ON r.simulado_id = s.id "
                "WHERE s.id = %s GROUP BY s.id", (sid,))
            row = cur.fetchone()
            if row:
                row["nota"] = (round(100 * row["acertos"] / row["n_questoes"],
                                     1) if row["n_questoes"] else 0)
                data = str(row["data"])
                row["data"] = (data[8:10] + "/" + data[5:7] + "/" + data[:4]
                               + " " + data[11:16])
                simulados.append(row)
        conn.commit()
        cur.execute(
            "SELECT q.tema, COUNT(*) total, "
            "SUM(CASE WHEN r.correta = 1 THEN 1 ELSE 0 END) acertos "
            "FROM respostas r JOIN questoes q ON q.id = r.questao_id "
            "WHERE r.resposta_marcada IS NOT NULL GROUP BY q.tema "
            "ORDER BY total DESC")
        por_tema = cur.fetchall()
        cur.execute(
            "SELECT COUNT(DISTINCT questao_id) c FROM respostas "
            "WHERE resposta_marcada IS NOT NULL")
        respondidas = cur.fetchone()["c"]
    return render_template("historico.html", simulados=simulados,
                           por_tema=por_tema, respondidas=respondidas)


@app.route("/historico/<int:sid>")
@exige_login
def historico_simulado(sid):
    with pg() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        _corrigir(cur, sid)
        cur.execute(
            "SELECT q.id, q.tema, q.enunciado, q.gabarito, q.justificativa, "
            "r.resposta_marcada, r.correta FROM respostas r "
            "JOIN questoes q ON q.id = r.questao_id "
            "WHERE r.simulado_id = %s ORDER BY r.id", (sid,))
        questoes = cur.fetchall()
        conn.commit()
    if not questoes:
        abort(404)
    acertos = sum(1 for q in questoes if q["correta"])
    total = len(questoes)
    por_tema = {}
    for q in questoes:
        d = por_tema.setdefault(q["tema"] or "(sem tema)",
                                {"acertos": 0, "total": 0})
        d["total"] += 1
        d["acertos"] += 1 if q["correta"] else 0
    return render_template("resultado.html", nota=round(100 * acertos / total,
                                                        1) if total else 0,
                           acertos=acertos, total=total,
                           por_tema=por_tema, questoes=questoes,
                           historico=True)


if __name__ == "__main__":
    app.run(debug=True)

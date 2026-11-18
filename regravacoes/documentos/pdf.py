"""
Geração dos PDFs com ReportLab (Python puro: funciona em hospedagem sem bibliotecas de sistema). A4, fundo branco,
legível em preto e branco. Os textos vêm de texto_declaracao.py e texto_recibo.py; os dados da empresa, da tela Empresa.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from PIL import Image as ImagemPIL
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import texto_declaracao as decl
from . import texto_recibo as rec

MARGEM = 2 * cm
ESTILO = ParagraphStyle("base", fontName="Helvetica", fontSize=10.5, leading=15, alignment=TA_LEFT)
JUSTIFICADO = ParagraphStyle("justificado", parent=ESTILO, alignment=TA_JUSTIFY, leading=17)
TITULO = ParagraphStyle("titulo", parent=ESTILO, fontName="Helvetica-Bold", fontSize=22, leading=28, alignment=TA_CENTER)
CENTRO = ParagraphStyle("centro", parent=ESTILO, alignment=TA_CENTER)
PEQUENO = ParagraphStyle("pequeno", parent=ESTILO, fontSize=8, leading=10, textColor=colors.HexColor("#444444"))
LEGENDA = ParagraphStyle("legenda", parent=CENTRO, fontSize=9, leading=11)


def _p(texto, estilo=ESTILO):
    return Paragraph(texto, estilo)


def _logo(logo_bytes):
    """Logo da configuração da empresa ou, se não houver, a logo padrão do sistema. Largura fixa de 6 cm."""
    if logo_bytes:
        fonte = BytesIO(logo_bytes)
    else:
        fonte = settings.BASE_DIR / "static" / "img" / "logo-vap.png"
    with ImagemPIL.open(fonte) as imagem:
        largura, altura = imagem.size
    if logo_bytes:
        fonte.seek(0)
    alvo = 5.5 * cm
    return Image(fonte, width=alvo, height=alvo * altura / largura, hAlign="CENTER")


def _quadro(linhas):
    tabela = Table([[_p(f"<b>{escape(r)}</b>"), _p(escape(v))] for r, v in linhas], colWidths=[5.2 * cm, None])
    tabela.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor("#999999")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return tabela


def _assinaturas(esquerda, direita):
    """Duas linhas de assinatura lado a lado: cada lado é (nome, [linhas menores])."""
    def lado(nome, detalhes):
        blocos = [Spacer(1, 1.6 * cm), Table([[""]], colWidths=[6.5 * cm], rowHeights=[1],
                                             style=[("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black)]),
                  _p(f"<b>{escape(nome)}</b>", CENTRO)]
        blocos += [_p(escape(d), LEGENDA) for d in detalhes if d]
        return blocos
    celulas = [lado(*esquerda)] + ([lado(*direita)] if direita[0] or direita[1] else [])   # um lado só (recibo)
    tabela = Table([celulas], colWidths=[8.5 * cm] * len(celulas), hAlign="LEFT")
    tabela.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return KeepTogether(tabela)


def _rodape(empresa, numero, emitido_em, substitui):
    def desenhar(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#444444"))
        linha = f"Documento nº {numero} · emitido em {emitido_em:%d/%m/%Y %H:%M}"
        if substitui:
            linha += f" · substitui o documento nº {substitui}"
        canvas.drawString(MARGEM, 1.6 * cm, empresa.get("rodape") or empresa.get("razao_social", ""))
        canvas.drawString(MARGEM, 1.2 * cm, linha)
        canvas.restoreState()
    return desenhar


def _montar(elementos, numero, emitido_em, substitui, empresa, titulo):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=1.6 * cm,
                            bottomMargin=2.4 * cm, title=f"{titulo} {numero}", author=empresa.get("razao_social", ""))
    rodape = _rodape(empresa, numero, emitido_em, substitui)
    doc.build(elementos, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()


def gerar_declaracao(dados, numero, emitido_em, substitui=None):
    e = dados["empresa"]
    esc = {k: escape(v) for k, v in e.items()}
    paragrafo = decl.PARAGRAFO.format(
        razao_social=esc["razao_social"], cnpj=esc["cnpj"], endereco=esc["endereco"], telefones=esc["telefones"],
        servico=escape(dados["servico"]))
    r = decl.ROTULOS
    linhas = [(r["proprietario"], dados["proprietario"]), (r["veiculo"], dados["veiculo"]), (r["ano"], dados["ano"]),
              (r["cor"], dados["cor"]), (r["placa"], dados["placa"])]
    if dados["chassi"]:
        linhas.append((r["chassi"], dados["chassi"]))
    if dados["motor"]:
        linhas.append((r["motor"], dados["motor"]))
    linhas += [(r["data"], dados["data_servico"]), (r["solicitante"], dados["solicitante"])]
    tecnico = dados["tecnico"]
    solicitante_assina = (dados["solicitante"], [decl.LEGENDA_SOLICITANTE])
    elementos = [
        _logo(dados.get("logo")), Spacer(1, 0.9 * cm),
        _p(f"{escape(e['cidade'])}, {emitido_em:%d/%m/%Y}"), Spacer(1, 0.9 * cm),
        _p(decl.TITULO, TITULO), Spacer(1, 0.7 * cm),
        _p(paragrafo, JUSTIFICADO), Spacer(1, 0.6 * cm),
        _quadro(linhas), Spacer(1, 0.4 * cm),
        _assinaturas((tecnico["nome"], [tecnico["funcao"], f"Credencial {tecnico['credencial']}" if tecnico["credencial"] else ""]),
                     solicitante_assina),
    ]
    return _montar(elementos, numero, emitido_em, substitui, e, decl.TITULO)


def gerar_recibo(dados, numero, emitido_em, substitui=None):
    e = dados["empresa"]
    paragrafo = rec.PARAGRAFO.format(
        cliente=escape(dados["cliente"]), valor=escape(dados["valor"]), extenso=escape(dados["extenso"]),
        servico=escape(dados["servico"].lower()), veiculo=escape(dados["veiculo"]), placa=escape(dados["placa"]))
    r = rec.ROTULOS
    linhas = [(r["forma"], dados["forma"]), (r["data"], dados["data"]),
              (r["empresa"], f"{e['razao_social']} · CNPJ {e['cnpj']}")]
    resp = dados["responsavel"]
    elementos = [
        _logo(dados.get("logo")), Spacer(1, 0.7 * cm),
        _p(rec.TITULO, TITULO), Spacer(1, 0.2 * cm),
        _p(f"<b>Nº {escape(numero)}</b>", CENTRO), Spacer(1, 0.7 * cm),
        _p(f"<b>Valor: {escape(dados['valor'])}</b>", ParagraphStyle("valor", parent=ESTILO, fontSize=14, leading=18)),
        Spacer(1, 0.4 * cm),
        _p(paragrafo, JUSTIFICADO), Spacer(1, 0.6 * cm),
        _quadro(linhas), Spacer(1, 0.5 * cm),
        _p(f"{escape(e['cidade'])}, {dados['data']}"), Spacer(1, 0.2 * cm),
        _assinaturas((resp["nome"], [resp["funcao"], rec.LEGENDA_ASSINATURA]), ("", [])),
    ]
    return _montar(elementos, numero, emitido_em, substitui, e, rec.TITULO)

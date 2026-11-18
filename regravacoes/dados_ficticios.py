"""
Regravações FICTÍCIAS (parceiros, técnicos, placas e clientes inventados, empresa de exemplo) com anexos gerados por
código (nunca documentos reais). Usado pelo comando `popular_dados`.

Os concluídos e recebidos passam por regras.registrar_andamento, então geram atendimento e recebimento de verdade.
A empresa de exemplo começa com "[EXEMPLO]" para `limpar_dados_teste` saber que pode apagá-la.
"""
import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.utils import timezone
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from atendimentos.models import Atendimento
from cadastros.models import Cliente
from financeiro.regras import mes_fechado
from servicos.models import TipoServico
from vip_preparacao import fotos
from vip_preparacao.models import Cor

from . import regras
from .documentos import emissao
from .models import (
    AnexoRegravacao, ConfiguracaoEmpresa, DocumentoEmitido, HistoricoRegravacao, Parceiro, RegistroRegravacao,
    Tecnico,
)

MARCADOR_EMPRESA = "[EXEMPLO] "
PARCEIROS = [("Despachante Exemplo Ltda", "(00) 90000-1001", "Despachante"), ("Loja de Peças Modelo", "(00) 90000-1002", "Loja de autopeças"),
             ("Oficina Teste do Zé", "(00) 90000-1003", "Oficina mecânica"), ("Consultor Fictício Souza", "(00) 90000-1004", "Consultor automotivo")]
TECNICOS = [("Técnico Exemplo da Silva", "Técnico responsável", "REG-0001"), ("Técnica Modelo Pereira", "Técnica em vistoria", "REG-0002"),
            ("Técnico Teste Almeida", "Técnico responsável", "")]
# (placa, marca, modelo, ano/modelo, cor, chassi, motor)  — todos inventados
VEICULOS = [
    ("RGV1A11", "Fiat", "Uno Exemplo", "2011/2012", Cor.BRANCO, "9BD00000000000001", "MTR100001"),
    ("RGV2B22", "Chevrolet", "Onix Teste", "2018/2019", Cor.PRATA, "9BG00000000000002", "MTR100002"),
    ("RGV3C33", "Volkswagen", "Gol Modelo", "2015/2015", Cor.PRETO, "9BW00000000000003", "MTR100003"),
    ("RGV4D44", "Hyundai", "HB20 Fictício", "2020/2021", Cor.VERMELHO, "9BH00000000000004", "MTR100004"),
    ("RGV5E55", "Ford", "Ka Exemplo", "2013/2014", Cor.AZUL, "9BF00000000000005", "MTR100005"),
    ("RGV6F66", "Renault", "Sandero Teste", "2016/2017", Cor.CINZA, "9BR00000000000006", "MTR100006"),
    ("RGV7G77", "Toyota", "Etios Modelo", "2017/2017", Cor.BRANCO, "9BT00000000000007", "MTR100007"),
    ("RGV8H88", "Honda", "Fit Fictício", "2012/2013", Cor.VERDE, "9BH00000000000008", "MTR100008"),
    ("RGV9J99", "Jeep", "Renegade Exemplo", "2019/2020", Cor.PRETO, "9BJ00000000000009", "MTR100009"),
    ("RGV0K00", "Nissan", "March Teste", "2014/2015", Cor.AMARELO, "9BN00000000000010", "MTR100010"),
    ("RGW1A11", "Peugeot", "208 Modelo", "2021/2022", Cor.VINHO, "9BP00000000000011", "MTR100011"),
    ("RGW2B22", "Citroën", "C3 Exemplo", "2016/2016", Cor.BEGE, "9BC00000000000012", "MTR100012"),
]


def pdf_de_exemplo(texto):
    saida = BytesIO()
    c = canvas.Canvas(saida, pagesize=A4)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 760, "ANEXO FICTÍCIO DE EXEMPLO")
    c.setFont("Helvetica", 12)
    c.drawString(72, 730, texto)
    c.drawString(72, 710, "Gerado por código para testes. Não é um documento real.")
    c.save()
    return saida.getvalue()


def anexo_pdf(texto):
    return {"conteudo": pdf_de_exemplo(texto), "miniatura": None, "content_type": "application/pdf",
            "nome_original": f"{texto.lower().replace(' ', '_')}.pdf"}


def anexo_imagem(texto, indice):
    imagem = Image.new("RGB", (1000, 700), (60 + indice * 15 % 120, 90, 120))
    desenho = ImageDraw.Draw(imagem)
    desenho.rectangle((30, 30, 970, 670), outline=(255, 255, 255), width=4)
    desenho.text((60, 60), "ANEXO FICTÍCIO DE EXEMPLO", fill=(255, 255, 255))
    desenho.text((60, 100), texto, fill=(255, 255, 255))
    grande, _ = fotos._jpeg(imagem, 1000, 80)
    mini, _ = fotos._jpeg(imagem, fotos.LADO_MINIATURA, 75)
    return {"conteudo": grande, "miniatura": mini, "content_type": "image/jpeg", "nome_original": f"{texto.lower().replace(' ', '_')}.jpg"}


def apagar_registros():
    """--refazer: apaga documentos, anexos e registros; devolve os atendimentos gerados (quem chama os trata)."""
    for anexo in AnexoRegravacao.objects.all():
        for arquivo in (anexo.arquivo, anexo.miniatura):
            if arquivo:
                try:
                    arquivo.storage.delete(arquivo.name)
                except Exception:
                    pass
    DocumentoEmitido.objects.all().delete()
    atendimentos = list(RegistroRegravacao.objects.exclude(atendimento=None).values_list("atendimento_id", flat=True))
    HistoricoRegravacao.objects.all().delete()
    RegistroRegravacao.objects.all().delete()
    return atendimentos


def preparar_empresa():
    """Empresa de EXEMPLO (só preenche se ainda estiver vazia) e os 3 tipos de serviço de Regravação."""
    cfg = ConfiguracaoEmpresa.obter()
    if not cfg.razao_social:
        cfg.razao_social = MARCADOR_EMPRESA + "Empresa Fictícia Ltda - ME"
        cfg.cnpj, cfg.cidade = "11.222.333/0001-81", "Cidade Exemplo"
        cfg.endereco = "Rua das Flores, 100 - Sala 2 - Centro, Cidade Exemplo - UF, 00000-000"
        cfg.telefones, cfg.rodape = "(00) 0000-0000 / (00) 90000-0000", "Empresa fictícia - documento de exemplo gerado pelo sistema"
        cfg.responsavel_recibo_nome, cfg.responsavel_recibo_funcao = "Responsável Exemplo", "Sócio-administrador"
    for campo, nome in (("servico_motor", "Regravação de motor"), ("servico_chassi", "Regravação de chassi"),
                        ("servico_motor_chassi", "Regravação de motor e chassi")):
        if getattr(cfg, f"{campo}_id") is None:
            servico = TipoServico.objects.filter(nome=nome, categoria=TipoServico.Categoria.REGRAVACAO).first() or \
                TipoServico.objects.create(nome=nome, categoria=TipoServico.Categoria.REGRAVACAO,
                                           valor_padrao={"servico_motor": "450.00", "servico_chassi": "400.00"}.get(campo, "800.00"))
            setattr(cfg, campo, servico)
    cfg.save()
    return cfg


def gerar_regravacoes(usuarios, refazer=False):
    """Retorna quantas regravações foram criadas (0 se já existiam e refazer=False)."""
    if RegistroRegravacao.objects.exists():
        if not refazer:
            return 0
        ids = apagar_registros()
        from financeiro.models import Recebimento, RegistroAuditoria
        recebimentos = list(Recebimento.objects.filter(atendimento_id__in=ids).values_list("id", flat=True))
        Recebimento.objects.filter(id__in=recebimentos).delete()
        RegistroAuditoria.objects.filter(entidade=RegistroAuditoria.Entidade.RECEBIMENTO, objeto_id__in=recebimentos).delete()
        Atendimento.objects.filter(pk__in=ids).delete()
    clientes = list(Cliente.objects.order_by("id"))
    if not clientes:
        return 0

    admin = usuarios[0]
    rnd = random.Random(2030)
    hoje = timezone.localdate()
    dia = lambda n: hoje + timedelta(days=n)
    cfg = preparar_empresa()
    parceiros = [Parceiro.objects.get_or_create(nome=n, defaults={"telefone": t, "empresa_profissao": e})[0] for n, t, e in PARCEIROS]
    tecnicos = [Tecnico.objects.get_or_create(nome=n, defaults={"funcao": f, "credencial": c})[0] for n, f, c in TECNICOS]

    # (motor, chassi, parceiro?, agendada, concluída, valor, recebido?, forma, completo(anexos)?, emitir docs?)
    planos = [
        (False, True, 0, None, None, None, False, "", False, False),               # solicitada, sem valor
        (True, False, 1, dia(3), None, "450.00", False, "", False, False),         # agendada
        (True, True, None, dia(5), None, "850.00", False, "", True, False),        # agendada, ambos, sem parceiro
        (False, True, 0, dia(-6), dia(-5), "400.00", False, "", True, False),      # concluída, recebimento pendente
        (True, False, 2, dia(-9), dia(-8), "450.00", False, "", False, False),     # concluída, autorização pendente
        (False, True, 1, dia(-12), dia(-10), "400.00", True, "pix", True, True),   # concluída e recebida, docs emitidos
        (True, True, 0, dia(-15), dia(-14), "850.00", True, "cartao_credito", True, True),
        (True, False, 3, dia(-20), dia(-18), "450.00", True, "dinheiro", True, False),
        (False, True, 2, dia(-4), dia(-3), "400.00", True, "transferencia", True, True),
        (True, False, None, None, None, "450.00", False, "", False, False),        # solicitada com valor
        (False, True, 3, dia(-2), None, "400.00", False, "", True, False),         # agendada (data no passado)
        (True, True, 1, dia(-7), None, "850.00", False, "", False, False),         # cancelada (abaixo)
    ]
    criadas = 0
    for i, (plano, (placa, marca, modelo, ano_modelo, cor, chassi, motor)) in enumerate(zip(planos, VEICULOS)):
        m, c, p, agendada, concluida, valor, recebido, forma, completo, emitir = plano
        cliente = clientes[i % len(clientes)]
        r = RegistroRegravacao.objects.create(
            parceiro=parceiros[p] if p is not None else None, cliente=cliente, placa=placa, marca=marca, modelo=modelo,
            ano_modelo=ano_modelo, cor=cor, chassi=chassi if c else "", numero_motor=motor if m else "",
            proprietario="" if i % 2 == 0 else f"Proprietário Fictício {i}", proprietario_e_cliente=i % 2 == 0,
            servico_motor=m, servico_chassi=c, data_agendada=agendada,
            valor=Decimal(valor) if valor else None, observacao="Regravação fictícia para testes." if i % 3 == 0 else "",
            criado_por=admin, alterado_por=admin)
        regras.registrar_criacao(r, admin)
        novos = {}
        if completo:
            if m:
                novos[AnexoRegravacao.Tipo.AUTORIZACAO_MOTOR] = anexo_pdf("Autorizacao de Motor")
            if c:
                novos[AnexoRegravacao.Tipo.AUTORIZACAO_CHASSI] = anexo_imagem("Autorizacao de Chassi", i)
            novos[AnexoRegravacao.Tipo.DOCUMENTO_VEICULO] = anexo_imagem("Documento do Veiculo", i + 1)
        elif i % 2 == 0:
            novos[AnexoRegravacao.Tipo.LAUDO_ECV] = anexo_pdf("Laudo ECV")
        if novos:
            regras.salvar_anexos(r, novos, set(), admin)

        if i == 11:                                  # a última é cancelada
            regras.cancelar(r, "Cliente desistiu (exemplo)", admin)
        elif concluida:
            data_receb = dia(-1 - i % 3)
            if mes_fechado(data_receb):              # mês fechado no Financeiro: usa hoje
                data_receb = hoje
            regras.registrar_andamento(
                r, admin, data_concluida=concluida, tecnico=tecnicos[i % len(tecnicos)],
                situacao="recebido" if recebido else "pendente", forma=forma, data_recebimento=data_receb if recebido else None)
            if emitir:
                emissao.emitir(r, DocumentoEmitido.Tipo.DECLARACAO, admin)
                emissao.emitir(r, DocumentoEmitido.Tipo.RECIBO, admin)
        criadas += 1
    return criadas

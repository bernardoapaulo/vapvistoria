"""
Registros de VIP/Preparação FICTÍCIOS (placas e clientes inventados) com fotos de exemplo geradas por código
(retângulos coloridos com texto): nunca fotos reais. Usado pelo comando `popular_dados`.

Os concluídos passam por regras.concluir, então geram atendimento e recebimento de verdade no Financeiro.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from PIL import Image, ImageDraw

from atendimentos.models import Atendimento
from cadastros.models import Cliente
from financeiro.regras import mes_fechado
from servicos.models import TipoServico

from . import fotos, regras
from .forms import servicos_disponiveis
from .models import Cor, FotoVip, ItemServicoVip, RegistroVip

POSICOES = [p for p, _ in FotoVip.Posicao.choices]
ROTULOS = dict(FotoVip.Posicao.choices)

# (placa, marca, modelo, versão, cor, ano)  — todos inventados
VEICULOS = [
    ("FIC1A23", "Fiat", "Argo", "Drive 1.3", Cor.BRANCO, 2021), ("MOD2B34", "Chevrolet", "Onix", "LT 1.0", Cor.PRATA, 2020),
    ("TST3C45", "Volkswagen", "Polo", "Highline", Cor.PRETO, 2022), ("EXE4D56", "Hyundai", "HB20", "Comfort", Cor.VERMELHO, 2019),
    ("DEM5E67", "Toyota", "Corolla", "XEi 2.0", Cor.CINZA, 2023), ("SIM6F78", "Honda", "Civic", "EXL", Cor.AZUL, 2018),
    ("FAK7G89", "Jeep", "Compass", "Longitude", Cor.BRANCO, 2022), ("ABC1234", "Renault", "Kwid", "Zen", Cor.LARANJA, 2020),
    ("QRS8H90", "Ford", "Ka", "SE 1.0", Cor.VERDE, 2017), ("NOV9J01", "Nissan", "Kicks", "Advance", Cor.VINHO, 2021),
    ("PRE0K12", "Peugeot", "208", "Griffe", Cor.BEGE, 2022), ("TIP1L23", "Citroën", "C4 Cactus", "Shine", Cor.DOURADO, 2019),
    ("LAB2M34", "Mitsubishi", "L200", "Triton", Cor.MARROM, 2020), ("VID3N45", "Kia", "Sportage", "EX", Cor.PRETO, 2021),
    ("CAR4P56", "Chevrolet", "Tracker", "Premier", Cor.CINZA, 2023),
]

CORES_FOTO = [(34, 80, 112), (56, 110, 140), (70, 90, 120), (90, 70, 110), (60, 100, 90), (110, 80, 70)]


def foto_de_exemplo(texto, indice):
    """Imagem simples gerada por código: fundo em gradiente suave + texto. Devolve (grande, miniatura)."""
    imagem = Image.new("RGB", (1280, 960), CORES_FOTO[indice % len(CORES_FOTO)])
    desenho = ImageDraw.Draw(imagem)
    for y in range(0, 960, 8):   # faixas leves para não parecer chapado
        tom = 12 + (y // 8) % 5 * 4
        desenho.rectangle((0, y, 1280, y + 4), fill=tuple(min(255, c + tom) for c in CORES_FOTO[indice % len(CORES_FOTO)]))
    desenho.rectangle((40, 40, 1240, 920), outline=(255, 255, 255), width=4)
    desenho.text((80, 80), "FOTO FICTÍCIA DE EXEMPLO", fill=(255, 255, 255))
    desenho.text((80, 130), texto, fill=(255, 255, 255))
    grande, _ = fotos._jpeg(imagem, 1280, 80)
    mini, _ = fotos._jpeg(imagem, fotos.LADO_MINIATURA, 75)
    return grande, mini


def apagar_registros():
    """Usado pelo --refazer-*: apaga os registros (e as fotos); atendimentos e recebimentos são tratados por quem chama."""
    for foto in FotoVip.objects.all():
        for arquivo in (foto.imagem, foto.miniatura):
            try:
                arquivo.storage.delete(arquivo.name)
            except Exception:
                pass
    atendimentos = list(ItemServicoVip.objects.exclude(atendimento=None).values_list("atendimento_id", flat=True))
    RegistroVip.objects.all().delete()          # os itens saem junto (cascade)
    return atendimentos


def gerar_registros_vip(usuarios, refazer=False):
    """Retorna quantos registros foram criados (0 se já existiam e refazer=False)."""
    if RegistroVip.objects.exists():
        if not refazer:
            return 0
        ids = apagar_registros()
        # os atendimentos e recebimentos gerados na conclusão saem junto (só no banco fictício)
        from financeiro.models import Recebimento, RegistroAuditoria
        recebimentos = list(Recebimento.objects.filter(atendimento_id__in=ids).values_list("id", flat=True))
        Recebimento.objects.filter(id__in=recebimentos).delete()
        RegistroAuditoria.objects.filter(entidade=RegistroAuditoria.Entidade.RECEBIMENTO, objeto_id__in=recebimentos).delete()
        Atendimento.objects.filter(pk__in=ids).delete()
    clientes = list(Cliente.objects.order_by("id"))
    servicos = list(servicos_disponiveis().filter(ativo=True))
    if not clientes or not servicos:
        return 0

    rnd = random.Random(2028)
    hoje = timezone.localdate()
    admin = usuarios[0]
    dia = lambda n: hoje + timedelta(days=n)

    # (prep, vip, devolução, concluir?, forma) — mistura de etapas, atrasados e concluídos
    modelos = [
        (dia(3), None, None, False), (dia(1), None, dia(6), False),                      # aguardando
        (dia(-3), None, dia(2), False), (dia(-1), None, None, False),                     # em preparação
        (dia(-6), dia(-2), dia(3), False), (dia(-4), dia(-1), None, False), (dia(-5), dia(0), dia(4), False),  # VIP
        (dia(-8), dia(-4), dia(0), False), (dia(-7), dia(-3), dia(0), False),             # pronto p/ devolução
        (dia(-12), dia(-8), dia(-3), False), (dia(-10), dia(-6), dia(-2), False), (dia(-15), dia(-11), dia(-5), False),  # atrasados
        (dia(-22), dia(-19), dia(-16), "pix"), (dia(-18), dia(-15), dia(-12), "cartao_credito"),
        (dia(-9), dia(-6), dia(-4), "dinheiro"),                                         # concluídos
    ]
    criados = 0
    for i, ((prep, vip, devolucao, concluir), (placa, marca, modelo, versao, cor, ano)) in enumerate(zip(modelos, VEICULOS)):
        r = RegistroVip.objects.create(
            cliente=clientes[i % len(clientes)], placa=placa, marca=marca, modelo=modelo, versao=versao, cor=cor,
            ano=ano, chassi=f"9BWZZZ377VT{rnd.randint(100000, 999999)}" if i % 3 == 0 else "",
            data_preparacao=prep, data_vip=vip, data_devolucao=devolucao,
            previsao_pagamento=(devolucao or dia(7)) + timedelta(days=rnd.randint(0, 5)),
            nota_fiscal=f"NF-{1000 + i}" if i % 2 == 0 else "", observacao="Registro fictício para testes." if i % 4 == 0 else "",
            criado_por=admin, alterado_por=admin)
        # 1, 2 ou 3 serviços (em ciclo); o primeiro escolhido pelo índice, os outros em seguida
        for n in range(i % 3 + 1):
            servico = servicos[(i + n * 3) % len(servicos)]
            ItemServicoVip.objects.create(
                registro=r, servico=servico, valor=servico.valor_padrao,
                observacao="Item fictício" if n == 2 else "")
        regras.recalcular_total(r)
        regras.registrar_criacao(r, admin)

        # Fotos de exemplo: entrada em quase todos; saída só nos concluídos e em alguns prontos
        entrada = {("entrada", p): foto_de_exemplo(f"{placa} · entrada · {ROTULOS[p]}", i + n)
                   for n, p in enumerate(POSICOES[: 4 + (i % 3)]) if i % 5 != 4}
        saida = {}
        if concluir or i in (7,):
            saida = {("saida", p): foto_de_exemplo(f"{placa} · saída · {ROTULOS[p]}", i + n + 2)
                     for n, p in enumerate(POSICOES[:4])}
        if entrada or saida:
            regras.salvar_fotos(r, {**entrada, **saida}, set(), admin)

        if concluir:
            recebimento = dia(-1 - i % 3)
            if mes_fechado(recebimento):   # mês fechado no Financeiro: lança hoje
                recebimento = hoje
            regras.concluir(r, None, concluir, recebimento, admin, False)
        criados += 1
    return criados

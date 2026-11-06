"""
Popula o banco com dados FICTÍCIOS para testes e cria dois usuários de teste.
Pode ser executado várias vezes sem duplicar registros.

Uso:  python manage.py popular_dados
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from agenda.dados_ficticios import gerar_agendamentos
from atendimentos.dados_ficticios import gerar_atendimentos
from cadastros.models import Aluno, Cliente, Veiculo
from contas.permissoes import ADMINISTRADOR, FUNCIONARIO, criar_grupos
from financeiro.dados_ficticios import gerar_despesas
from servicos.models import TipoServico

CATEGORIA = TipoServico.Categoria

USUARIOS = [
    # (username, senha, grupo, é_staff)
    ("admin_teste", "Admin@12345", ADMINISTRADOR, True),
    ("funcionario_teste", "Func@12345", FUNCIONARIO, False),
]

# CPFs/CNPJs abaixo são números de exemplo com dígitos verificadores válidos.
CLIENTES = [
    ("Maria Fictícia da Silva", "529.982.247-25", "(11) 90000-0001", "(11) 90000-0001", "maria.ficticia@exemplo.com"),
    ("João Exemplo Pereira", "111.444.777-35", "(11) 90000-0002", "", "joao.exemplo@exemplo.com"),
    ("Auto Peças Modelo Ltda", "11.222.333/0001-81", "(11) 3000-0003", "(11) 90000-0003", "contato@autopecasmodelo.exemplo"),
    ("Carla Teste Souza", "", "(11) 90000-0004", "(11) 90000-0004", ""),
    ("Roberto Imaginário Lima", "", "(11) 90000-0005", "", ""),
    # Clientes extras (etapa 4): dão variedade ao ranking e ao dashboard
    ("Paulo Modelo Andrade", "", "(11) 90000-0006", "", ""),
    ("Fernanda Ficção Costa", "", "(11) 90000-0007", "(11) 90000-0007", ""),
    ("Transportes Imaginários Ltda", "", "(11) 3000-0008", "", "contato@transportes.exemplo"),
    ("Marcos Teste Oliveira", "", "(11) 90000-0009", "", ""),
    ("Juliana Exemplo Rocha", "", "(11) 90000-0010", "(11) 90000-0010", ""),
    ("Locadora Fictícia Veículos", "", "(11) 3000-0011", "", "contato@locadora.exemplo"),
    ("Sérgio Inventado Martins", "", "(11) 90000-0012", "", ""),
]

def gerar_cpf(base):
    """Monta um CPF fictício válido a partir de 9 dígitos (calcula os 2 verificadores)."""
    digitos = [int(c) for c in base]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        digitos.append((soma * 10 % 11) % 10)
    d = "".join(map(str, digitos))
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


ALUNOS = [
    # nome, cpf, celular, e-mail, nascimento, sexo, endereço, cep, cliente vinculado
    ("Pedro Aluno Fictício", gerar_cpf("123456789"), "(11) 91111-0001", "pedro.aluno@exemplo.com",
     date(1995, 3, 14), "M", "Rua Exemplo, 100 - Bairro Teste, Cidade Modelo", "01001-000", None),
    ("Ana Estudante Exemplo", gerar_cpf("987654321"), "(11) 91111-0002", "ana.estudante@exemplo.com",
     date(2000, 11, 2), "F", "Avenida Imaginária, 250 - Centro, Cidade Modelo", "02002-000", "Carla Teste Souza"),
    ("Lucas Curso Teste", gerar_cpf("246813579"), "(11) 91111-0003", "",
     date(1988, 7, 30), "M", "Travessa Fictícia, 45 - Vila Teste, Cidade Modelo", "03003-000", None),
    ("Marina Curso Exemplo", gerar_cpf("135792468"), "(11) 91111-0004", "",
     date(1992, 5, 21), "F", "Rua Inventada, 12 - Centro, Cidade Modelo", "04004-000", "Paulo Modelo Andrade"),
    ("Rafael Treino Fictício", gerar_cpf("864209753"), "(11) 91111-0005", "",
     date(1999, 1, 9), "M", "Alameda Teste, 300 - Jardim Modelo, Cidade Modelo", "05005-000", None),
    ("Beatriz Aprendiz Teste", gerar_cpf("112233445"), "(11) 91111-0006", "",
     date(1985, 9, 17), "F", "Rua Exemplo, 77 - Vila Fictícia, Cidade Modelo", "06006-000", "Fernanda Ficção Costa"),
]

VEICULOS = [
    # placa, marca, modelo, ano, cor, proprietário
    ("ABC1234", "Fiat", "Uno", 2012, "Branco", "Maria Fictícia da Silva"),
    ("BRA2E19", "Volkswagen", "Gol", 2020, "Prata", "Maria Fictícia da Silva"),
    ("QWE5R67", "Chevrolet", "Onix", 2022, "Preto", "João Exemplo Pereira"),
    ("XYZ9876", "Ford", "Ka", 2015, "Vermelho", "Auto Peças Modelo Ltda"),
    ("FGH3J45", "Honda", "Civic", 2019, "Cinza", "Carla Teste Souza"),
    ("KLM7890", "Toyota", "Corolla", 2010, "Azul", "Roberto Imaginário Lima"),
    ("DEF4G56", "Renault", "Sandero", 2018, "Branco", "Paulo Modelo Andrade"),
    ("MNO1P23", "Hyundai", "HB20", 2021, "Prata", "Fernanda Ficção Costa"),
    ("RST8U90", "Mercedes-Benz", "Sprinter", 2017, "Branco", "Transportes Imaginários Ltda"),
    ("VWX2Y34", "Fiat", "Fiorino", 2016, "Branco", "Transportes Imaginários Ltda"),
    ("AAA1B23", "Jeep", "Renegade", 2022, "Preto", "Marcos Teste Oliveira"),
    ("CCC4D56", "Nissan", "Kicks", 2020, "Vermelho", "Juliana Exemplo Rocha"),
    ("EEE7F89", "Volkswagen", "Polo", 2023, "Cinza", "Locadora Fictícia Veículos"),
    ("GGG0H12", "Chevrolet", "Tracker", 2023, "Azul", "Locadora Fictícia Veículos"),
    ("JJJ3K45", "Honda", "CG 160", 2019, "Vermelho", "Sérgio Inventado Martins"),
]

SERVICOS = [
    ("Vistoria cautelar - carro", CATEGORIA.VISTORIA, "250.00"),
    ("Vistoria cautelar - moto", CATEGORIA.VISTORIA, "180.00"),
    ("Regravação de chassi", CATEGORIA.REGRAVACAO, "400.00"),
    ("Regravação de motor", CATEGORIA.REGRAVACAO, "450.00"),
    ("Curso de capacitação veicular", CATEGORIA.CAPACITACAO, "900.00"),
    ("Limpeza completa", CATEGORIA.LIMPEZA, "120.00"),
    ("Limpeza simples", CATEGORIA.LIMPEZA, "60.00"),
    ("Reparo de farol", CATEGORIA.REPAROS, "150.00"),
]


class Command(BaseCommand):
    help = "Cria dados fictícios (clientes, alunos, veículos, serviços, atendimentos) e usuários de teste."

    def add_arguments(self, parser):
        parser.add_argument(
            "--refazer-atendimentos", action="store_true",
            help="Apaga TODOS os atendimentos (e agendamentos) existentes e gera os fictícios de novo.",
        )
        parser.add_argument(
            "--refazer-agenda", action="store_true",
            help="Apaga TODOS os agendamentos (e os atendimentos extras da agenda) e gera os fictícios de novo.",
        )

        parser.add_argument(
            "--refazer-financeiro", action="store_true",
            help="Apaga TODAS as despesas, fechamentos de mês e auditoria deles e gera os fictícios de novo.",
        )

    def handle(self, *args, **options):
        criar_grupos()
        Usuario = get_user_model()
        from django.contrib.auth.models import Group

        usuarios = []
        for username, senha, grupo, staff in USUARIOS:
            usuario, criado = Usuario.objects.get_or_create(username=username, defaults={"is_staff": staff})
            if criado:
                usuario.set_password(senha)
                usuario.save()
            usuario.groups.set([Group.objects.get(name=grupo)])
            usuarios.append(usuario)

        clientes = {}
        for nome, doc, tel, whats, email in CLIENTES:
            cliente, _ = Cliente.objects.get_or_create(
                nome=nome,
                defaults={"cpf_cnpj": doc, "telefone": tel, "whatsapp": whats, "email": email,
                          "data_cadastro": date.today()},
            )
            clientes[nome] = cliente

        for nome, cpf, celular, email, nasc, sexo, endereco, cep, cliente_nome in ALUNOS:
            dados = {"cpf": cpf, "celular": celular, "email": email, "data_nascimento": nasc,
                     "sexo": sexo, "endereco": endereco, "cep": cep, "cliente": clientes.get(cliente_nome)}
            aluno, criado = Aluno.objects.get_or_create(nome=nome, defaults=dados)
            if not criado and not aluno.cpf:
                # Aluno fictício criado numa versão anterior (sem os campos novos): completa os dados.
                for campo, valor in dados.items():
                    setattr(aluno, campo, valor)
                aluno.save()

        for placa, marca, modelo, ano, cor, dono in VEICULOS:
            Veiculo.objects.get_or_create(
                placa=placa,
                defaults={"marca": marca, "modelo": modelo, "ano": ano, "cor": cor,
                          "proprietario": clientes[dono]},
            )

        for nome, categoria, valor in SERVICOS:
            TipoServico.objects.get_or_create(
                nome=nome, defaults={"categoria": categoria, "valor_padrao": valor},
            )

        criados = gerar_atendimentos(usuarios, refazer=options["refazer_atendimentos"])
        if criados:
            self.stdout.write(f"{criados} atendimentos fictícios gerados.")
        else:
            self.stdout.write("Atendimentos já existem; nada foi alterado (use --refazer-atendimentos para recriar).")

        agendados = gerar_agendamentos(usuarios, refazer=options["refazer_agenda"])
        if agendados:
            self.stdout.write(f"{agendados} agendamentos fictícios gerados.")
        else:
            self.stdout.write("Agendamentos já existem; nada foi alterado (use --refazer-agenda para recriar).")

        despesas = gerar_despesas(usuarios, refazer=options["refazer_financeiro"])
        if despesas:
            self.stdout.write(f"{despesas} despesas fictícias geradas (e 2 meses fechados).")
        else:
            self.stdout.write("Despesas já existem; nada foi alterado (use --refazer-financeiro para recriar).")

        self.stdout.write(self.style.SUCCESS("Dados fictícios criados."))
        self.stdout.write("Usuários de teste:")
        for username, senha, grupo, _ in USUARIOS:
            self.stdout.write(f"  {username} / {senha}  ({grupo})")

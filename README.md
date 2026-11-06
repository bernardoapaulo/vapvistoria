# VAP Vistoria — Sistema de Gestão

Sistema web em Django para a VAP Vistoria (vistoria cautelar, regravação, capacitação, limpeza e pequenos reparos).

**Etapa atual: 6 — Interface** (identidade visual sobre as etapas 1 a 5; nenhuma regra de negócio mudou).

## Como rodar (Windows / PowerShell)

```powershell
# 1. Criar e ativar o ambiente virtual
py -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
copy .env.example .env      # depois edite o .env e troque a SECRET_KEY

# 4. Criar o banco (isto também cria os grupos Administrador e Funcionário)
python manage.py migrate

# 5. Popular com dados FICTÍCIOS e criar usuários de teste
python manage.py popular_dados

# 6. Iniciar o servidor
python manage.py runserver
```

Acesse http://127.0.0.1:8000/

Se o PowerShell bloquear o `Activate.ps1`, use `.\venv\Scripts\python` no lugar de `python`.

### Usuários de teste (criados por `popular_dados`)

| Usuário | Senha | Perfil |
|---|---|---|
| `admin_teste` | `Admin@12345` | Administrador |
| `funcionario_teste` | `Func@12345` | Funcionário |

Use estas senhas apenas em desenvolvimento. Para criar um administrador real: `python manage.py createsuperuser` e depois adicione o usuário ao grupo *Administrador* em `/admin/`.

### Testes

```powershell
python manage.py test
```

## Perfis e permissões

| | Clientes / Alunos / Veículos | Tipos de serviço | Atendimentos | Agenda | Dashboard | Financeiro |
|---|---|---|---|---|---|---|
| **Administrador** | consultar, criar, editar, excluir | consultar, criar, editar, excluir | tudo, incluindo valor/desconto, reabrir e excluir | tudo, incluindo excluir, reabrir cancelados e editar o horário de funcionamento | tudo, incluindo faturamento, ticket médio, a receber, top clientes e exportação CSV | tudo: recebimentos, estornos, despesas, contas a receber/pagar, fluxo de caixa, relatório mensal e fechamento de mês |
| **Funcionário** | consultar, criar, editar, excluir | somente consultar | consultar, criar, editar, mudar status e registrar recebimento (sem valor/desconto, reabrir ou excluir) | ver a agenda de todos, criar, editar, mudar status e remarcar (sem excluir nem reabrir) | só indicadores operacionais (quantidades, status, agenda, taxas); sem faturamento, valores, ranking por receita nem CSV | **nada**, exceto registrar um recebimento (com a data de hoje) na tela do atendimento; não edita, não estorna e não vê totais nem despesas |

Os grupos são criados automaticamente após `migrate` (`contas/apps.py`) ou manualmente com `python manage.py criar_grupos`. As regras ficam em um só lugar: `contas/permissoes.py`.

## Atendimentos (etapa 2)

Cada serviço prestado ou solicitado é um **atendimento** (`atendimentos/`): cliente, tipo de serviço, veículo (ou aluno, nas capacitações), valor, pagamento e status (Solicitado → Agendado → Em andamento → Concluído; Cancelado a qualquer momento antes de concluir).

- O valor cobrado é **copiado** do tipo de serviço na criação; alterar o valor padrão depois não muda atendimentos antigos.
- Toda mudança de status, pagamento e valor gera uma linha no **histórico** (quem, quando, de/para), exibido como linha do tempo. A gravação passa sempre por `atendimentos/historico.py`.
- Concluído/Cancelado só volta a "Em andamento" (reabertura) pelo Administrador; o Funcionário ainda pode registrar o pagamento.
- Permissões personalizadas: `atendimentos.alterar_valor` e `atendimentos.reabrir` (só Administrador).
- Para gerar de novo os atendimentos fictícios (apaga TODOS os atendimentos): `python manage.py popular_dados --refazer-atendimentos`.

## Agenda (etapa 3)

App `agenda/`: cada **agendamento** é um horário marcado para um atendimento (um atendimento pode ter vários: remarcações, aulas de um curso).

- **Telas** (menu *Agenda*): calendário (mês/semana/dia; no celular abre na lista do dia), lista com filtros, pendências, e o horário de funcionamento (só Administrador). A página inicial tem o bloco *Hoje*.
- **Calendário:** [FullCalendar 6](https://fullcalendar.io/) (licença MIT), servido localmente (`static/vendor/fullcalendar/`, versão 6.1.15). Foi escolhido por já trazer mês/semana/dia/lista, funcionar bem em tela de toque e dispensar build (Node). Os eventos vêm de `/agenda/eventos/` e levam só horário, serviço, cliente e status (sem telefone, CPF ou endereço). As cores dos status ficam em variáveis de `tokens.css`.
- **Regras** (`agenda/regras.py`): criar agendamento move o atendimento *Solicitado* para *Agendado*; *Iniciar* põe o atendimento em *Em andamento*; *Concluir* pergunta se o atendimento também deve ser concluído; *Remarcar* cria um novo agendamento ligado ao antigo (que vira *Remarcado*). Tudo vai para o histórico do atendimento.
- **Avisos (não bloqueiam):** conflito de horário (mesmo responsável ou o local fixo da empresa) e horário fora do expediente. O formulário lista os conflitos e só salva marcando *Salvar mesmo assim*.
- **Travas:** Cancelado, Não compareceu e Remarcado só o Administrador altera ou reabre (permissão `agenda.reabrir`).
- **Fuso:** `America/Sao_Paulo` em todo o projeto (`USE_TZ=True`).
- Dados fictícios da agenda: `python manage.py popular_dados` (só cria se não houver agendamentos). Para refazer: `python manage.py popular_dados --refazer-agenda`.

## Dashboard (etapa 4)

App `dashboard/` (sem modelos): tudo é calculado a partir dos atendimentos e agendamentos.

- **Onde ficam as regras:** `dashboard/services.py` concentra TODAS as definições (cabeçalho do arquivo) e só usa agregações do banco (`Count`, `Sum`, `TruncMonth`, `ExtractWeekDay`...). `periodos.py` calcula períodos e o comparativo; `graficos.py` monta os dados dos gráficos. Views e templates só exibem. O módulo financeiro (etapa 5) pode reutilizar `services.py`.
- **Definições:** serviço realizado = atendimento *Concluído* (pela data do atendimento); faturamento = soma de (valor cobrado − desconto) dos concluídos, sem cancelados; ticket médio = faturamento ÷ serviços; taxas de cancelamento, conclusão e não comparecimento, clientes novos/recorrentes: veja a caixa “Como os números são calculados” na própria tela.
- **Gráficos:** [Chart.js 4](https://www.chartjs.org/) (licença MIT) servido localmente (`static/vendor/chartjs/`, versão 4.4.3). Os dados vão em JSON na página, e `static/js/dashboard.js` desenha tudo; as cores vêm de variáveis CSS (`--cor-grafico-*`, `--cor-categoria-*`).
- **Componentes:** `templates/dashboard/componentes/` (indicador, variação, gráfico, “sem dados”, definições) para reutilizar no financeiro.
- **Privacidade e permissões:** a parte financeira só é calculada e enviada para quem tem `atendimentos.ver_faturamento`; o CSV exige `atendimentos.exportar_dados`. Ambas são só do Administrador. Para o Funcionário a chave `financeiro` nem existe no contexto da página.
- **CSV:** separador `;`, UTF-8 com BOM e vírgula decimal (abre direto no Excel em português); células de texto que começam com `=`, `+`, `-` ou `@` recebem um apóstrofo para não virarem fórmula.
- **Cache:** não usado (consultas agregadas rápidas); se ficar lento, um cache de ~5 min em `DashboardView` resolve.
- **Dados fictícios:** 12 meses com sazonalidade, ~320 atendimentos, clientes recorrentes e clientes que “chegam” no meio do ano. Para regenerar: `python manage.py popular_dados --refazer-atendimentos` (apaga todos os atendimentos e agendamentos e recria).

## Financeiro (etapa 5)

App `financeiro/` (somente Administrador). O dinheiro nasce dos atendimentos, sem digitar duas vezes.

- **Regimes:** *caixa* (resultado, entradas e saídas, fluxo): receita = recebimento na **data do recebimento**; despesa = pagamento na **data do pagamento**. *Competência* (só “a receber”, “a pagar” e lucro por serviço): o que foi vendido ou devido. Resultado = recebido − despesas pagas; margem = resultado ÷ recebido. Todas as definições estão no cabeçalho de `financeiro/services.py` e num texto de ajuda na tela. O faturamento do Dashboard de desempenho (serviço concluído) não mudou; a tela do Financeiro mostra a diferença entre os dois.
- **Recebimentos:** um atendimento pode ter vários (pagamento em partes). A **situação do pagamento é calculada** (Pendente, Parcial, Pago) a partir da soma dos recebimentos contra o valor devido; `valor_pago` e `situacao_pagamento` no atendimento são só uma cópia gravada por `financeiro.regras.recalcular_pagamento`. O total recebido não ultrapassa o devido. O Administrador **estorna** (fica registrado com motivo, nunca é apagado).
- **Despesas:** categorias editáveis (12 padrão), vencimento e pagamento, fornecedor, comprovante (PDF/JPG/PNG até 5 MB, fora de pastas públicas em `arquivos_privados/`, servido só por `/financeiro/despesas/<id>/comprovante/` a quem tem acesso) e vínculo opcional a um tipo de serviço (despesa direta). **Recorrentes:** marque “repetir todo mês”; as dos próximos 2 meses são geradas ao abrir o Financeiro ou por `python manage.py gerar_despesas_recorrentes`, sem duplicar (há também uma restrição única no banco).
- **Fechamento de mês:** mês fechado bloqueia criar, editar e estornar lançamentos com data nele (recebimento: a data do recebimento; despesa: o pagamento ou, se não paga, o vencimento). Reabrir fica registrado com usuário e data. Só meses já encerrados podem ser fechados.
- **Auditoria:** todo lançamento guarda quem criou e quem alterou por último; alterações de valor, estornos, pagamentos, exclusões e fechamentos entram em `RegistroAuditoria`; recebimentos também entram no histórico do atendimento.
- **Telas:** resumo (com gráficos), a receber (faixas de atraso), a pagar (faixas de vencimento), fluxo de caixa (+ projeção de 30 dias), recebimentos, despesas, categorias, resultado do mês (imprimível e CSV para Excel) e meses.
- **Valores:** sempre `Decimal`, arredondados em centavos (meio para cima) por `financeiro/dinheiro.py`, exibidos como R$ 1.234,56. Operações que mexem em mais de uma tabela usam `transaction.atomic`.
- **Dados fictícios:** `python manage.py popular_dados --refazer-atendimentos --refazer-financeiro` recria atendimentos com recebimentos (à vista, parcelados, parciais, pendentes e atrasados), 12 meses de despesas (fixas, variáveis, recorrentes, em aberto e vencidas) e 2 meses fechados.

## Interface (etapa 6)

- **Estilo único:** fundo em gradiente azul-petróleo/marinho com brilho aqua suave, cartões de vidro fosco, destaque em menta, títulos condensados e números grandes. Um tema só, mas tudo em variáveis (`tokens.css`), então um segundo tema é só repetir os valores.
- **Tudo local (LGPD e funciona sem internet):** fontes Inter e Barlow Condensed (licença SIL OFL 1.1), ícones Lucide (ISC), Chart.js e FullCalendar (MIT). As licenças estão em `static/vendor/fonts/` e `static/icons/`.
- **Convenção de classes:** BEM em português: `bloco`, `bloco__elemento`, `bloco--modificador` (ex.: `.indicador__titulo`, `.btn--secundario`); estados como `.ativo`. Sem `style="..."` nos templates.
- **Vidro com bom senso:** `backdrop-filter` só onde há suporte (senão, cor sólida semitransparente); tabelas e listas usam vidro opaco, sem blur.
- **Barra lateral:** só ícones; abre ao passar o mouse ou focar com o teclado. Abaixo de 900 px vira gaveta (botão no topo). Tabelas largas viram cartões no celular.
- **Impressão:** em `@media print` os tokens trocam para fundo branco e texto escuro, sem vidro nem gradiente, com a logo no topo.
- **Logo:** o arquivo recebido é pequeno (225 px, JPEG). A versão clara (`logo-vap-clara.png`, barra lateral e favicon) e a versão sobre fundo transparente (`logo-vap.png`, login, erros e impressão) foram geradas dele; para ficar nítida em tamanho grande, troque por um SVG ou PNG de alta resolução.
- Páginas `403`, `404` e `500` com a identidade da empresa e caminho de volta.

## Publicar na Vercel

O projeto já tem `vercel.json` (roda `build.py`: migra o banco e, se pedido, carrega dados de exemplo) e a Vercel detecta o Django pelo `manage.py`. O que a Vercel **não** oferece é disco: o SQLite não funciona lá, então é preciso um Postgres externo.

1. **Banco:** no painel da Vercel, aba *Storage*, crie um Postgres (Neon) e conecte ao projeto; isso define `DATABASE_URL` sozinho. (Ou use qualquer Postgres e defina `DATABASE_URL` à mão.)
2. **Variáveis** (Settings > Environment Variables): `SECRET_KEY` (uma chave longa e aleatória; gere com `python -c "import secrets; print(secrets.token_urlsafe(50))"`) e `DEBUG=False`. Para domínio próprio, também `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS`.
3. **Deploy:** *Redeploy*. O build aplica as migrações no Postgres.
4. **Dados e usuários de teste (no próprio deploy):** em Environment Variables defina `CARREGAR_DADOS_FICTICIOS=1`, `SENHA_ADMIN_TESTE` e `SENHA_FUNCIONARIO_TESTE` (senhas suas, **não** as do README: o comando recusa carregar na Vercel sem elas) e faça *Redeploy*. O `build.py` migra o banco e cria os dados fictícios e os usuários `admin_teste` e `funcionario_teste`. Depois pode apagar `CARREGAR_DADOS_FICTICIOS`; rodar de novo não duplica nada. (Alternativa pelo seu computador: defina `DATABASE_URL`, as duas senhas e rode `python manage.py popular_dados`.)

Limites conhecidos: arquivos enviados (fotos e documentos de alunos, comprovantes) ficam em `/tmp` e **somem** quando a função é reciclada; para produção real, use um armazenamento externo (S3, Vercel Blob). Os arquivos estáticos são servidos pela CDN da Vercel.

## Estrutura

```
config/      configurações do Django (settings lê o .env) e URLs
contas/      login/logout, página inicial, grupos e comandos (criar_grupos, popular_dados)
cadastros/   Cliente, Aluno, Veículo (modelos, formulários, validadores, views)
  crud.py    views genéricas de CRUD reutilizadas por todos os cadastros
servicos/    Tipo de serviço
atendimentos/ Atendimento, HistoricoAtendimento, regras, formulário e telas
dashboard/   services.py (cálculos), periodos.py, graficos.py, views e CSV
financeiro/  Recebimento, Despesa, categorias, fechamento de mês, regras.py (gravações), services.py (cálculos), graficos.py
agenda/      Agendamento, horário de funcionamento, regras (regras.py), calendário e pendências
templates/   HTML (base.html tem o menu lateral)
static/css/  tokens.css (cores, vidro, tipografia, espaços), base.css (layout e componentes), modulos.css (início, agenda, dashboard, financeiro), impressao.css
static/vendor/ Chart.js, FullCalendar e fontes (Inter, Barlow Condensed) locais, com licenças
static/icons/ sprite.svg (ícones Lucide) · static/img/ logo, favicon
```

Para mudar o visual, altere `static/css/tokens.css`; os templates usam apenas classes semânticas.

## Banco de dados

Padrão: SQLite (`db.sqlite3`). Para PostgreSQL, defina no `.env`:

```
DATABASE_URL=postgres://usuario:senha@servidor:5432/nome_do_banco
```

Em produção também use `DEBUG=False`, uma `SECRET_KEY` própria e `ALLOWED_HOSTS` com o domínio.

## Privacidade (LGPD)

- Listagens mostram só o necessário (ex.: cliente: nome, telefone, nº de veículos).
- CPF/CNPJ aparece mascarado na tela de detalhe.
- Documentos dos alunos (foto, antecedentes, certidões etc.) ficam na pasta `media/` (fora do git) e só são abertos por usuários logados com permissão, pela rota protegida `/alunos/<id>/documento/<campo>/`. Aceita PDF/JPG/PNG até 5 MB; os arquivos recebem nomes aleatórios e são apagados do disco quando o aluno é excluído ou o arquivo é removido. **Em produção, a pasta `media/` precisa de armazenamento persistente e backup.**
- O repositório não contém dados reais; `popular_dados` usa apenas dados inventados.
- `.env` e `db.sqlite3` estão no `.gitignore`.

## Próximas etapas

6. Interface (feita)

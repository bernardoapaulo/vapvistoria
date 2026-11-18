"""
Views do módulo Regravações. Segurança: login + permissão em TODAS (verificadas no servidor) e o módulo inteiro só
aparece para os perfis liberados na central de acesso (hoje, só o Administrador). Documentos, anexos e PDFs só saem por
views com login e permissão; nada fica em pasta pública.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef, ProtectedError, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from cadastros.models import Cliente, Veiculo
from cadastros.validators import normalizar_placa
from financeiro.models import FormaPagamento
from servicos.models import TipoServico
from vip_preparacao.models import Cor

from . import regras
from .documentos import emissao
from .forms import (
    ConcluirRegravacaoForm, EmpresaForm, FiltroRegravacaoForm, ParceiroForm, RegistroRegravacaoForm, TecnicoForm,
)
from .models import (
    AnexoRegravacao, ConfiguracaoEmpresa, DocumentoEmitido, Parceiro, RegistroRegravacao, Tecnico,
)

APP = "regravacoes"
Status = RegistroRegravacao.Status
Situacao = RegistroRegravacao.Situacao


def _erro(e):
    return " ".join(e.messages)


def _concluida_q():
    return Q(cancelada=False, data_concluida__isnull=False, tecnico__isnull=False)


def filtro_status(status):
    """Mesma regra de RegistroRegravacao.status, escrita como consulta (o status é calculado, não gravado)."""
    if status == Status.CANCELADA:
        return Q(cancelada=True)
    if status == Status.CONCLUIDA:
        return _concluida_q()
    nao_cancelada_nem_concluida = Q(cancelada=False) & ~_concluida_q()
    if status == Status.AGENDADA:
        return nao_cancelada_nem_concluida & Q(data_agendada__isnull=False)
    if status == Status.SOLICITADA:
        return nao_cancelada_nem_concluida & Q(data_agendada__isnull=True)
    return Q()


def _voltar_para(request, padrao):
    """Endereço de retorno (?next=) só aceito se for do próprio site."""
    destino = request.GET.get("next", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino.split("?")[0]
    return padrao


# ---------- Regravações: lista ----------
class RegravacaoLista(PermissionRequiredMixin, ListView):
    permission_required = f"{APP}.view_registroregravacao"
    model = RegistroRegravacao
    template_name = "regravacoes/lista.html"
    paginate_by = settings.ITENS_POR_PAGINA

    def get_queryset(self):
        g = self.request.GET
        qs = (RegistroRegravacao.objects.select_related("parceiro", "cliente", "tecnico").prefetch_related("anexos"))
        self.termo = g.get("q", "").strip()
        if self.termo:
            placa = normalizar_placa(self.termo)
            busca = (Q(cliente__nome__icontains=self.termo) | Q(chassi__icontains=self.termo.upper())
                     | Q(proprietario__icontains=self.termo) | Q(parceiro__nome__icontains=self.termo)
                     | Q(marca__icontains=self.termo) | Q(modelo__icontains=self.termo))
            if placa:
                busca |= Q(placa__icontains=placa)
            qs = qs.filter(busca)
        if g.get("status") in Status.values:
            qs = qs.filter(filtro_status(g["status"]))
        servico = g.get("servico")
        if servico == "motor":
            qs = qs.filter(servico_motor=True, servico_chassi=False)
        elif servico == "chassi":
            qs = qs.filter(servico_chassi=True, servico_motor=False)
        elif servico == "ambos":
            qs = qs.filter(servico_motor=True, servico_chassi=True)
        if g.get("recebimento") in Situacao.values:
            qs = qs.filter(recebimento_situacao=g["recebimento"])
        self.filtro = FiltroRegravacaoForm(g)
        ordem = "-criado_em"
        if self.filtro.is_valid():
            c = self.filtro.cleaned_data
            if c["parceiro"]:
                qs = qs.filter(parceiro=c["parceiro"])
            if c["tecnico"]:
                qs = qs.filter(tecnico=c["tecnico"])
            campo = c["campo_data"] or "criado_em"
            sufixo = "__date" if campo == "criado_em" else ""
            if c["de"]:
                qs = qs.filter(**{f"{campo}{sufixo}__gte": c["de"]})
            if c["ate"]:
                qs = qs.filter(**{f"{campo}{sufixo}__lte": c["ate"]})
            ordem = c["ordem"] or ordem
        return qs.order_by(ordem, "-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        u = self.request.user
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        ctx.update(
            termo=self.termo, querystring=parametros.urlencode(), f=self.request.GET,
            status_opcoes=Status.choices, recebimento_opcoes=Situacao.choices,
            parceiros=Parceiro.objects.order_by("nome").only("id", "nome"),
            tecnicos=Tecnico.objects.order_by("nome").only("id", "nome"),
            campos_data=FiltroRegravacaoForm.CAMPOS_DATA, ordens=FiltroRegravacaoForm.ORDENS,
            pode_editar=u.has_perm(f"{APP}.change_registroregravacao"),
            pode_concluir=u.has_perm(f"{APP}.concluir_regravacao"),
            pode_emitir=u.has_perm(f"{APP}.emitir_documento_regravacao"),
            ver_valor=u.has_perm(f"{APP}.alterar_valor_regravacao") or u.has_perm(f"{APP}.view_registroregravacao"),
            formas=FormaPagamento.choices, tecnicos_ativos=Tecnico.objects.filter(ativo=True).order_by("nome"),
            hoje=timezone.localdate(),
        )
        return ctx


# ---------- Regravações: formulário ----------
class _Formulario:
    template_name = "regravacoes/form.html"
    model = RegistroRegravacao

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def _anexos_existentes(self):
        if not getattr(self, "object", None) or not self.object.pk:
            return {}
        return {a.tipo: a for a in self.object.anexos.all()}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx["form"]
        ctx.update(
            cores=Cor.choices, campos_anexos=form.campos_de_anexos(self._anexos_existentes()),
            pode_gerenciar_tecnicos=self.request.user.has_perm(f"{APP}.add_tecnico"),
            pode_gerenciar_parceiros=self.request.user.has_perm(f"{APP}.add_parceiro"),
        )
        return ctx

    def form_valid(self, form):
        try:
            r = form.salvar()
        except ValidationError as e:
            messages.error(self.request, _erro(e))
            return self.form_invalid(form)
        self.object = r
        messages.success(self.request, self.mensagem_sucesso)
        if r.lancado_em and (timezone.now() - r.lancado_em).total_seconds() < 5:
            messages.success(self.request, "Concluída e recebida: lançada no Financeiro.")
        return redirect(r.get_absolute_url())

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível salvar. Corrija os campos destacados.")
        return super().form_invalid(form)


class RegravacaoCriar(_Formulario, PermissionRequiredMixin, CreateView):
    permission_required = f"{APP}.add_registroregravacao"
    form_class = RegistroRegravacaoForm
    mensagem_sucesso = "Regravação cadastrada com sucesso."

    def get_initial(self):
        inicial = super().get_initial()
        for campo, modelo in (("cliente", Cliente), ("parceiro", Parceiro), ("tecnico", Tecnico)):
            valor = self.request.GET.get(campo, "")        # volta do cadastro de cliente/parceiro/técnico
            if valor.isdigit() and modelo.objects.filter(pk=valor).exists():
                inicial[campo] = int(valor)
        return inicial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = "Nova regravação"
        return ctx


class RegravacaoEditar(_Formulario, PermissionRequiredMixin, UpdateView):
    permission_required = f"{APP}.change_registroregravacao"
    form_class = RegistroRegravacaoForm
    mensagem_sucesso = "Alterações salvas com sucesso."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.has_perm(self.permission_required):
            r = get_object_or_404(RegistroRegravacao, pk=kwargs["pk"])
            if r.lancado and not request.user.has_perm(f"{APP}.editar_lancada_regravacao"):
                messages.error(request, "Esta regravação já foi concluída e recebida (lançada no Financeiro) e está "
                                        "travada. Só o Administrador edita; ou reabra para corrigir.")
                return redirect(r.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = f"Editar regravação #{self.object.pk}"
        return ctx


# ---------- Regravações: detalhe e ações ----------
class RegravacaoDetalhe(PermissionRequiredMixin, DetailView):
    permission_required = f"{APP}.view_registroregravacao"
    template_name = "regravacoes/detalhe.html"
    queryset = RegistroRegravacao.objects.select_related(
        "parceiro", "cliente", "tecnico", "atendimento", "criado_por", "alterado_por").prefetch_related("anexos")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        r, u = self.object, self.request.user
        cfg = ConfiguracaoEmpresa.obter()
        documentos = list(r.documentos.select_related("emitido_por").prefetch_related("substituido_por"))
        ctx.update(
            historico=r.historico.select_related("usuario"), documentos=documentos,
            anexos_por_tipo={a.tipo: a for a in r.anexos.all()},
            tipos_anexo=AnexoRegravacao.Tipo.choices, exigidos=r.anexos_exigidos,
            pendencias_declaracao=emissao.exigencias(r, DocumentoEmitido.Tipo.DECLARACAO, cfg),
            pendencias_recibo=emissao.exigencias(r, DocumentoEmitido.Tipo.RECIBO, cfg),
            pode_editar=u.has_perm(f"{APP}.change_registroregravacao") and (
                not r.lancado or u.has_perm(f"{APP}.editar_lancada_regravacao")),
            pode_concluir=u.has_perm(f"{APP}.concluir_regravacao") and not r.cancelada and not r.lancado,
            pode_reabrir=u.has_perm(f"{APP}.reabrir_regravacao") and r.lancado,
            pode_excluir=u.has_perm(f"{APP}.delete_registroregravacao") and not r.lancado,
            pode_cancelar=u.has_perm(f"{APP}.change_registroregravacao") and not r.cancelada and not r.lancado,
            pode_emitir=u.has_perm(f"{APP}.emitir_documento_regravacao"),
            formas=FormaPagamento.choices, tecnicos_ativos=Tecnico.objects.filter(ativo=True).order_by("nome"),
            hoje=timezone.localdate(),
        )
        return ctx


class RegravacaoConcluir(PermissionRequiredMixin, View):
    """Pop-up "Concluir / receber": data do serviço, técnico e recebimento; lança no Financeiro se couber."""
    permission_required = f"{APP}.concluir_regravacao"

    def post(self, request, pk):
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        form = ConcluirRegravacaoForm(request.POST, registro=r)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar: " + "; ".join(" ".join(v) for v in form.errors.values()))
            destino = request.POST.get("voltar", "")
            if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
                return redirect(destino)           # volta para a lista (com os filtros) ou o detalhe de onde veio
            return redirect(r.get_absolute_url())
        c = form.cleaned_data
        try:
            regras.registrar_andamento(
                r, request.user, data_concluida=c["data_concluida"], tecnico=c["tecnico"], situacao=c["situacao"],
                forma=c["forma"], data_recebimento=c["data_recebimento"])
        except ValidationError as e:
            messages.error(request, _erro(e))
        else:
            r.refresh_from_db()
            messages.success(request, "Lançada no Financeiro: concluída e recebida." if r.lancado
                             else "Andamento salvo.")
        return redirect(r.get_absolute_url())


class RegravacaoReabrir(PermissionRequiredMixin, View):
    permission_required = f"{APP}.reabrir_regravacao"

    def post(self, request, pk):
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        try:
            regras.reabrir(r, request.user)
        except ValidationError as e:
            messages.error(request, _erro(e))
        else:
            messages.success(request, "Regravação reaberta. O recebimento foi estornado e consta no histórico.")
        return redirect(r.get_absolute_url())


class RegravacaoCancelar(PermissionRequiredMixin, View):
    permission_required = f"{APP}.change_registroregravacao"

    def post(self, request, pk):
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        try:
            regras.cancelar(r, request.POST.get("motivo", ""), request.user)
        except ValidationError as e:
            messages.error(request, _erro(e))
        else:
            messages.success(request, "Regravação cancelada.")
        return redirect(r.get_absolute_url())


class RegravacaoExcluir(PermissionRequiredMixin, View):
    permission_required = f"{APP}.delete_registroregravacao"

    def _bloqueio(self, r):
        if r.lancado or r.atendimento_id:
            return ("Esta regravação já foi lançada no Financeiro e não pode ser excluída. "
                    "Se foi lançada por engano, reabra.")
        if r.documentos.exists():
            return "Esta regravação tem documentos emitidos (Declaração/Recibo) e não pode ser excluída. Cancele-a."
        return ""

    def get(self, request, pk):
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        if self._bloqueio(r):
            messages.error(request, self._bloqueio(r))
            return redirect(r.get_absolute_url())
        return render(request, "confirmar_exclusao.html", {"object": r, "nome_modelo": "regravação"})

    def post(self, request, pk):
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        if self._bloqueio(r):
            messages.error(request, self._bloqueio(r))
            return redirect(r.get_absolute_url())
        arquivos = [(a.arquivo.storage, a.arquivo.name) for a in r.anexos.all()] + [
            (a.miniatura.storage, a.miniatura.name) for a in r.anexos.all() if a.miniatura]
        try:
            r.delete()
        except ProtectedError:
            messages.error(request, "Não foi possível excluir: a regravação está vinculada a outros dados.")
            return redirect(r.get_absolute_url())
        for armazenamento, nome in arquivos:
            try:
                armazenamento.delete(nome)
            except Exception:
                pass
        messages.success(request, "Regravação excluída com sucesso.")
        return redirect("regravacao_lista")


# ---------- Documentos e anexos (sempre com login e permissão) ----------
class DocumentoEmitir(PermissionRequiredMixin, View):
    """Emite (ou reaproveita, se nada mudou) a Declaração/Recibo e abre o PDF."""
    permission_required = f"{APP}.emitir_documento_regravacao"

    def post(self, request, pk, tipo):
        if tipo not in DocumentoEmitido.Tipo.values:
            raise Http404
        r = get_object_or_404(RegistroRegravacao, pk=pk)
        try:
            documento, novo = emissao.emitir(r, tipo, request.user)
        except ValidationError as e:
            for mensagem in e.messages:
                messages.error(request, mensagem)
            return redirect(r.get_absolute_url())
        if novo:
            messages.success(request, f"{documento.get_tipo_display()} nº {documento.numero} emitida.")
        return redirect("documento_baixar", pk=documento.pk)


class DocumentoBaixar(PermissionRequiredMixin, View):
    permission_required = f"{APP}.view_registroregravacao"

    def get(self, request, pk):
        documento = get_object_or_404(DocumentoEmitido.objects.select_related("registro"), pk=pk)
        emissao.registrar_download(documento, request.user)
        resposta = HttpResponse(bytes(documento.pdf), content_type="application/pdf")
        nome = f"{documento.tipo}-{documento.ano}-{documento.sequencia:04d}.pdf"
        resposta["Content-Disposition"] = f'inline; filename="{nome}"'
        resposta["Cache-Control"] = "private, no-store"
        resposta["X-Content-Type-Options"] = "nosniff"
        return resposta


class AnexoBaixar(PermissionRequiredMixin, View):
    permission_required = f"{APP}.view_registroregravacao"

    def get(self, request, pk, tamanho):
        if tamanho not in ("arquivo", "mini"):
            raise Http404
        anexo = get_object_or_404(AnexoRegravacao, pk=pk)
        arquivo = anexo.arquivo if tamanho == "arquivo" else anexo.miniatura
        if not arquivo:
            raise Http404
        try:
            resposta = FileResponse(arquivo.open("rb"), content_type=anexo.content_type if tamanho == "arquivo" else "image/jpeg")
        except FileNotFoundError:
            raise Http404("Arquivo não encontrado.")
        resposta["Cache-Control"] = "private, no-store"
        resposta["X-Content-Type-Options"] = "nosniff"
        resposta["Content-Disposition"] = "inline"
        return resposta


class RegravacaoVeiculoPorPlaca(PermissionRequiredMixin, View):
    """Dados do veículo já cadastrado com esta placa (preenchimento do formulário). Só o necessário."""
    permission_required = f"{APP}.add_registroregravacao"

    def get(self, request):
        placa = normalizar_placa(request.GET.get("placa", ""))
        v = Veiculo.objects.filter(placa=placa).first() if placa else None
        if not v:
            return JsonResponse({"encontrado": False})
        chave = {c.label.lower(): c.value for c in Cor}.get((v.cor or "").strip().lower())
        return JsonResponse({
            "encontrado": True, "marca": v.marca, "modelo": v.modelo, "ano_modelo": f"{v.ano}/{v.ano}", "chassi": v.chassi,
            "cor": chave or Cor.OUTRA, "cor_outra": "" if chave else v.cor,
        })


# ---------- Parceiros ----------
class ParceiroLista(PermissionRequiredMixin, ListView):
    permission_required = f"{APP}.view_parceiro"
    template_name = "regravacoes/parceiro_lista.html"
    paginate_by = settings.ITENS_POR_PAGINA

    def get_queryset(self):
        qs = Parceiro.objects.annotate(
            total_indicacoes=Count("registros", filter=Q(registros__cancelada=False)),
            total_clientes=Count("registros__cliente", distinct=True, filter=Q(registros__cancelada=False)))
        self.termo = self.request.GET.get("q", "").strip()
        if self.termo:
            qs = qs.filter(Q(nome__icontains=self.termo) | Q(empresa_profissao__icontains=self.termo)
                           | Q(telefone__icontains=self.termo))
        situacao = self.request.GET.get("situacao", "ativos")
        if situacao == "ativos":
            qs = qs.filter(ativo=True)
        elif situacao == "inativos":
            qs = qs.filter(ativo=False)
        self.situacao = situacao
        return qs.order_by("nome")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(termo=self.termo, situacao=self.situacao, querystring="&".join(
            f"{k}={v}" for k, v in self.request.GET.items() if k != "page"),
            pode_criar=self.request.user.has_perm(f"{APP}.add_parceiro"),
            pode_editar=self.request.user.has_perm(f"{APP}.change_parceiro"))
        return ctx


class ParceiroDetalhe(PermissionRequiredMixin, DetailView):
    permission_required = f"{APP}.view_parceiro"
    model = Parceiro
    template_name = "regravacoes/parceiro_detalhe.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        p, u, g = self.object, self.request.user, self.request.GET
        base = p.registros.filter(cancelada=False)
        periodo = FiltroRegravacaoForm({"de": g.get("de", ""), "ate": g.get("ate", "")})
        de = ate = None
        if periodo.is_valid():
            de, ate = periodo.cleaned_data["de"], periodo.cleaned_data["ate"]
            if de:
                base = base.filter(criado_em__date__gte=de)
            if ate:
                base = base.filter(criado_em__date__lte=ate)
        clientes = (Cliente.objects.filter(regravacoes__in=base).annotate(indicacoes=Count("regravacoes", filter=Q(regravacoes__in=base)))
                    .order_by("nome").distinct())
        concluidas = base.filter(lancado_em__isnull=False)
        ctx.update(
            total_indicacoes=base.count(), clientes_indicados=list(clientes), total_clientes=len(clientes),
            total_concluidas=concluidas.count(), de=g.get("de", ""), ate=g.get("ate", ""),
            registros=base.select_related("cliente", "tecnico").prefetch_related("anexos").order_by("-criado_em")[:30],
            pode_editar=u.has_perm(f"{APP}.change_parceiro"),
            ver_faturamento=u.has_perm(f"{APP}.ver_faturamento_parceiro"),
        )
        if ctx["ver_faturamento"]:
            ctx["total_faturado"] = concluidas.aggregate(t=Sum("valor"))["t"] or Decimal("0.00")
        return ctx


class _FormParceiro:
    model = Parceiro
    form_class = ParceiroForm
    template_name = "regravacoes/parceiro_form.html"

    def get_success_url(self):
        destino = _voltar_para(self.request, "")
        if destino:
            return f"{destino}?parceiro={self.object.pk}"
        return reverse("parceiro_detalhe", args=[self.object.pk])

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, self.mensagem)
        return resposta


class ParceiroCriar(_FormParceiro, PermissionRequiredMixin, CreateView):
    permission_required = f"{APP}.add_parceiro"
    mensagem = "Parceiro cadastrado com sucesso."
    extra_context = {"titulo": "Novo parceiro indicador"}


class ParceiroEditar(_FormParceiro, PermissionRequiredMixin, UpdateView):
    permission_required = f"{APP}.change_parceiro"
    mensagem = "Parceiro atualizado."
    extra_context = {"titulo": "Editar parceiro indicador"}


class _AlternarAtivo(View):
    modelo = None
    destino = ""

    def post(self, request, pk):
        objeto = get_object_or_404(self.modelo, pk=pk)
        objeto.ativo = not objeto.ativo
        objeto.save(update_fields=["ativo"])
        messages.success(request, f"{objeto.nome} {'ativado' if objeto.ativo else 'desativado'}.")
        return redirect(self.destino)


class ParceiroAtivo(PermissionRequiredMixin, _AlternarAtivo):
    permission_required = f"{APP}.change_parceiro"
    modelo, destino = Parceiro, "parceiro_lista"


# ---------- Técnicos (só quem tem a permissão: Administrador) ----------
class TecnicoLista(PermissionRequiredMixin, ListView):
    permission_required = f"{APP}.view_tecnico"
    template_name = "regravacoes/tecnico_lista.html"
    queryset = Tecnico.objects.order_by("-ativo", "nome")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pode_gerenciar"] = self.request.user.has_perm(f"{APP}.change_tecnico")
        return ctx


class _FormTecnico:
    model = Tecnico
    form_class = TecnicoForm
    template_name = "regravacoes/tecnico_form.html"

    def get_success_url(self):
        destino = _voltar_para(self.request, "")
        if destino:
            return f"{destino}?tecnico={self.object.pk}"
        return reverse("tecnico_lista")

    def form_valid(self, form):
        resposta = super().form_valid(form)
        messages.success(self.request, "Técnico salvo com sucesso.")
        return resposta


class TecnicoCriar(_FormTecnico, PermissionRequiredMixin, CreateView):
    permission_required = f"{APP}.add_tecnico"
    extra_context = {"titulo": "Novo técnico responsável"}


class TecnicoEditar(_FormTecnico, PermissionRequiredMixin, UpdateView):
    permission_required = f"{APP}.change_tecnico"
    extra_context = {"titulo": "Editar técnico responsável"}


class TecnicoAtivo(PermissionRequiredMixin, _AlternarAtivo):
    permission_required = f"{APP}.change_tecnico"
    modelo, destino = Tecnico, "tecnico_lista"


# ---------- Empresa (dados usados nos PDFs) ----------
class Empresa(PermissionRequiredMixin, View):
    permission_required = f"{APP}.change_configuracaoempresa"
    template_name = "regravacoes/empresa.html"

    def _tela(self, request, form, status=200):
        cfg = ConfiguracaoEmpresa.obter()
        return render(request, self.template_name, {"form": form, "cfg": cfg, "tem_logo": bool(cfg.logo)}, status=status)

    def get(self, request):
        return self._tela(request, EmpresaForm(instance=ConfiguracaoEmpresa.obter()))

    def post(self, request):
        cfg = ConfiguracaoEmpresa.obter()
        if "criar_servicos" in request.POST:
            self._criar_servicos(request, cfg)
            return redirect("empresa")
        form = EmpresaForm(request.POST, request.FILES, instance=cfg)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar. Corrija os campos destacados.")
            return self._tela(request, form)
        form.save()
        messages.success(request, "Dados da empresa salvos.")
        return redirect("empresa")

    @staticmethod
    def _criar_servicos(request, cfg):
        """Cria os 3 tipos de serviço de Regravação que ainda não existirem (nada existente é alterado)."""
        padroes = (("servico_motor", "Regravação de motor"), ("servico_chassi", "Regravação de chassi"),
                   ("servico_motor_chassi", "Regravação de motor e chassi"))
        criados = 0
        for campo, nome in padroes:
            servico = TipoServico.objects.filter(nome=nome, categoria=TipoServico.Categoria.REGRAVACAO).first()
            if servico is None:
                servico = TipoServico.objects.create(
                    nome=nome, categoria=TipoServico.Categoria.REGRAVACAO, valor_padrao=Decimal("0.00"),
                    criado_por=request.user)
                criados += 1
            if getattr(cfg, f"{campo}_id") is None:
                setattr(cfg, campo, servico)
        cfg.save()
        messages.success(request, f"{criados} tipo(s) de serviço criado(s) e associado(s). Ajuste o valor padrão em Serviços, se quiser.")

"""
Views do módulo Vip/Preparação. Segurança: todas exigem login e permissão (verificadas no servidor); as fotos só
saem por VipFoto, que exige login e a permissão de consulta.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from cadastros.models import Cliente, Veiculo
from cadastros.validators import normalizar_placa
from financeiro.models import FormaPagamento
from servicos.models import TipoServico

from . import regras
from .forms import (
    ConcluirVipForm, FiltroVipForm, FotosSaidaForm, RegistroVipForm, servicos_disponiveis,
)
from .models import Cor, FotoVip, RegistroVip

Etapa = RegistroVip.Etapa
Status = RegistroVip.Status
APP = "vip_preparacao"


def _mensagem_de_erro(e):
    return " ".join(e.messages)


def filtro_da_etapa(etapa, hoje):
    """Mesma regra de RegistroVip.etapa, escrita como consulta (a etapa é calculada, não gravada)."""
    andamento = Q(status=Status.EM_ANDAMENTO)
    devolve_ate_hoje = Q(data_devolucao__lte=hoje)
    vip_ate_hoje = Q(data_vip__lte=hoje)
    if etapa == Etapa.ATRASADA:
        return andamento & Q(data_devolucao__lt=hoje)
    if etapa == Etapa.PRONTO:
        return andamento & Q(data_devolucao=hoje)
    if etapa == Etapa.VIP:
        return andamento & ~devolve_ate_hoje & vip_ate_hoje
    if etapa == Etapa.PREPARACAO:
        return andamento & ~devolve_ate_hoje & ~vip_ate_hoje & Q(data_preparacao__lte=hoje)
    if etapa == Etapa.AGUARDANDO:
        return andamento & ~devolve_ate_hoje & ~vip_ate_hoje & Q(data_preparacao__gt=hoje)
    if etapa == Etapa.CONCLUIDO:
        return Q(status=Status.CONCLUIDO)
    return Q()


class VipPermissao(PermissionRequiredMixin):
    permission_required = f"{APP}.view_registrovip"


class VipLista(VipPermissao, ListView):
    model = RegistroVip
    template_name = "vip_preparacao/lista.html"
    paginate_by = settings.ITENS_POR_PAGINA
    campos_busca = ["placa", "marca", "modelo", "versao", "cliente__nome", "nota_fiscal"]

    def get_queryset(self):
        g = self.request.GET
        qs = RegistroVip.objects.select_related("cliente", "servico")
        self.termo = g.get("q", "").strip()
        if self.termo:
            busca = Q()
            placa = normalizar_placa(self.termo)
            for campo in self.campos_busca:
                busca |= Q(**{f"{campo}__icontains": self.termo})
            if placa:
                busca |= Q(placa__icontains=placa)   # "abc-1234" acha ABC1234
            qs = qs.filter(busca)

        # Por padrão só "Em andamento"; ?status=todos mostra tudo
        self.status = g.get("status", Status.EM_ANDAMENTO)
        if self.status in Status.values:
            qs = qs.filter(status=self.status)
        self.etapa = g.get("etapa", "")
        if self.etapa in Etapa.values:
            qs = qs.filter(filtro_da_etapa(self.etapa, timezone.localdate()))

        self.filtro = FiltroVipForm(g)
        if self.filtro.is_valid():
            c = self.filtro.cleaned_data
            if c["cliente"]:
                qs = qs.filter(cliente=c["cliente"])
            if c["servico"]:
                qs = qs.filter(servico=c["servico"])
            campo = c["campo_data"] or "data_preparacao"
            if c["de"]:
                qs = qs.filter(**{f"{campo}__gte": c["de"]})
            if c["ate"]:
                qs = qs.filter(**{f"{campo}__lte": c["ate"]})
            ordem = c["ordem"] or "-data_preparacao"
        else:
            ordem = "-data_preparacao"
        return qs.order_by(ordem, "-id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parametros = self.request.GET.copy()
        parametros.pop("page", None)
        ctx.update(
            termo=self.termo, querystring=parametros.urlencode(), f=self.request.GET,
            status_atual=self.status, status_opcoes=Status.choices, etapa_opcoes=Etapa.choices,
            clientes=Cliente.objects.order_by("nome").only("id", "nome"),
            servicos=TipoServico.objects.order_by("nome").only("id", "nome"),
            campos_data=FiltroVipForm.CAMPOS_DATA, ordens=FiltroVipForm.ORDENS,
            pode_concluir=self.request.user.has_perm(f"{APP}.concluir_vip"),
            pode_alterar_valor=self.request.user.has_perm(f"{APP}.alterar_valor_vip"),
            pode_editar=self.request.user.has_perm(f"{APP}.change_registrovip"),
            hoje=timezone.localdate(), formas=FormaPagamento.choices,
        )
        return ctx


def _contexto_formulario(form, existentes):
    return {
        "cores": Cor.choices,
        "servicos_modal": servicos_disponiveis(form._servico_antes),
        "posicoes_entrada": form.campos_de_fotos("entrada", existentes),
        "posicoes_saida": form.campos_de_fotos("saida", existentes),
    }


class _FormularioVip:
    template_name = "vip_preparacao/form.html"
    model = RegistroVip

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_contexto_formulario(ctx["form"], self._fotos_existentes()))
        return ctx

    def _fotos_existentes(self):
        if not getattr(self, "object", None) or not self.object.pk:
            return {}
        return {(f.momento, f.posicao): f for f in self.object.fotos.all()}

    def form_valid(self, form):
        r = form.salvar()
        self.object = r
        messages.success(self.request, self.mensagem_sucesso)
        if form.nota_fiscal_repetida():
            messages.warning(self.request, f"Atenção: a nota fiscal {r.nota_fiscal} já existe em outro registro.")
        return redirect(r.get_absolute_url())

    def form_invalid(self, form):
        messages.error(self.request, "Não foi possível salvar. Corrija os campos destacados.")
        return super().form_invalid(form)


class VipCriar(_FormularioVip, PermissionRequiredMixin, CreateView):
    permission_required = f"{APP}.add_registrovip"
    form_class = RegistroVipForm
    mensagem_sucesso = "Registro criado com sucesso."

    def get_initial(self):
        """Volta do cadastro de cliente com ?cliente=<id>: já deixa o cliente escolhido."""
        inicial = super().get_initial()
        cliente = self.request.GET.get("cliente", "")
        if cliente.isdigit() and Cliente.objects.filter(pk=cliente).exists():
            inicial["cliente"] = int(cliente)
        return inicial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = "Novo registro VIP/Preparação"
        return ctx


class VipEditar(_FormularioVip, PermissionRequiredMixin, UpdateView):
    permission_required = f"{APP}.change_registrovip"
    mensagem_sucesso = "Alterações salvas com sucesso."

    def get_form_class(self):
        return RegistroVipForm

    def dispatch(self, request, *args, **kwargs):
        # Registro concluído: só o Administrador edita tudo; os demais só acrescentam fotos de saída.
        if request.user.is_authenticated and request.user.has_perm(self.permission_required):
            r = get_object_or_404(RegistroVip, pk=kwargs["pk"])
            if r.concluido and not request.user.has_perm(f"{APP}.editar_concluido_vip"):
                return VipFotosSaida.as_view()(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = f"Editar registro #{self.object.pk}"
        return ctx


class VipFotosSaida(PermissionRequiredMixin, View):
    """Registro concluído e usuário sem permissão de editar tudo: só envia fotos de saída."""
    permission_required = f"{APP}.change_registrovip"
    template_name = "vip_preparacao/fotos_saida.html"

    def _render(self, request, r, form):
        from django.shortcuts import render
        existentes = {(f.momento, f.posicao): f for f in r.fotos.all()}
        return render(request, self.template_name, {
            "object": r, "form": form, "posicoes_saida": form.campos_de_fotos("saida", existentes),
            "fotos_saida_existentes": [f for (m, _), f in existentes.items() if m == "saida"],
        })

    def get(self, request, pk):
        r = get_object_or_404(RegistroVip.objects.select_related("cliente", "servico"), pk=pk)
        return self._render(request, r, FotosSaidaForm(registro=r, usuario=request.user))

    def post(self, request, pk):
        r = get_object_or_404(RegistroVip.objects.select_related("cliente", "servico"), pk=pk)
        form = FotosSaidaForm(request.POST, request.FILES, registro=r, usuario=request.user)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar as fotos. Corrija os campos destacados.")
            return self._render(request, r, form)
        form.salvar()
        messages.success(request, "Fotos de saída salvas.")
        return redirect(r.get_absolute_url())


class VipDetalhe(VipPermissao, DetailView):
    template_name = "vip_preparacao/detalhe.html"
    queryset = RegistroVip.objects.select_related("cliente", "servico", "atendimento", "concluido_por", "criado_por", "alterado_por")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        r, u = self.object, self.request.user
        fotos = list(r.fotos.all())
        por_momento = {"entrada": {}, "saida": {}}
        for f in fotos:
            por_momento[f.momento][f.posicao] = f
        ordem = [p for p, _ in FotoVip.Posicao.choices]
        rotulo = dict(FotoVip.Posicao.choices)
        ctx.update(
            historico=r.historico.select_related("usuario"),
            fotos_entrada=[(rotulo[p], por_momento["entrada"][p]) for p in ordem if p in por_momento["entrada"]],
            fotos_saida=[(rotulo[p], por_momento["saida"][p]) for p in ordem if p in por_momento["saida"]],
            pode_editar=u.has_perm(f"{APP}.change_registrovip"),
            pode_concluir=u.has_perm(f"{APP}.concluir_vip") and not r.concluido,
            pode_reabrir=u.has_perm(f"{APP}.reabrir_vip") and r.concluido,
            pode_excluir=u.has_perm(f"{APP}.delete_registrovip"),
            pode_alterar_valor=u.has_perm(f"{APP}.alterar_valor_vip"),
            pode_editar_tudo=u.has_perm(f"{APP}.editar_concluido_vip"),
            formas=FormaPagamento.choices, hoje=timezone.localdate(),
        )
        if ctx["pode_concluir"]:
            ctx["concluir_form"] = ConcluirVipForm(registro=r, usuario=u)
        return ctx


class VipExcluir(PermissionRequiredMixin, View):
    permission_required = f"{APP}.delete_registrovip"
    template_name = "confirmar_exclusao.html"

    def _objeto(self, pk):
        return get_object_or_404(RegistroVip.objects.select_related("cliente"), pk=pk)

    def _contexto(self, r):
        return {"object": r, "nome_modelo": "registro VIP/Preparação"}

    def get(self, request, pk):
        from django.shortcuts import render
        r = self._objeto(pk)
        if r.atendimento_id:
            messages.error(request, "Este registro já gerou um atendimento e um recebimento no Financeiro e não pode "
                                    "ser excluído. Se foi lançado por engano, reabra o registro.")
            return redirect(r.get_absolute_url())
        return render(request, self.template_name, self._contexto(r))

    def post(self, request, pk):
        r = self._objeto(pk)
        if r.atendimento_id:
            messages.error(request, "Este registro já gerou um atendimento e não pode ser excluído. Use a reabertura.")
            return redirect(r.get_absolute_url())
        arquivos = [(f.imagem.storage, f.imagem.name) for f in r.fotos.all()] + \
                   [(f.miniatura.storage, f.miniatura.name) for f in r.fotos.all()]
        try:
            r.delete()
        except ProtectedError:
            messages.error(request, "Não foi possível excluir: o registro está vinculado a outros dados.")
            return redirect(r.get_absolute_url())
        for armazenamento, nome in arquivos:
            try:
                armazenamento.delete(nome)
            except Exception:
                pass
        messages.success(request, "Registro excluído com sucesso.")
        return redirect("vip_lista")


class VipConcluir(PermissionRequiredMixin, View):
    permission_required = f"{APP}.concluir_vip"

    def post(self, request, pk):
        r = get_object_or_404(RegistroVip, pk=pk)
        form = ConcluirVipForm(request.POST, registro=r, usuario=request.user)
        if not form.is_valid():
            erros = "; ".join(" ".join(v) for v in form.errors.values())
            messages.error(request, f"Não foi possível concluir: {erros}")
            return redirect(r.get_absolute_url())
        c = form.cleaned_data
        try:
            regras.concluir(r, c["valor"] if form.pode_alterar_valor else None, c["forma"], c["data"],
                            request.user, form.pode_alterar_valor)
        except ValidationError as e:
            messages.error(request, _mensagem_de_erro(e))
        else:
            messages.success(request, "Registro concluído e recebimento lançado no Financeiro.")
        return redirect(r.get_absolute_url())


class VipReabrir(PermissionRequiredMixin, View):
    permission_required = f"{APP}.reabrir_vip"

    def post(self, request, pk):
        r = get_object_or_404(RegistroVip, pk=pk)
        try:
            regras.reabrir(r, request.user)
        except ValidationError as e:
            messages.error(request, _mensagem_de_erro(e))
        else:
            messages.success(request, "Registro reaberto. O recebimento foi estornado e consta no histórico.")
        return redirect(r.get_absolute_url())


class VipFoto(VipPermissao, View):
    """Entrega a foto (ou a miniatura) só a quem está logado e tem permissão de consulta."""

    def get(self, request, pk, tamanho):
        if tamanho not in ("grande", "mini"):
            raise Http404
        foto = get_object_or_404(FotoVip, pk=pk)
        arquivo = foto.imagem if tamanho == "grande" else foto.miniatura
        try:
            resposta = FileResponse(arquivo.open("rb"), content_type="image/jpeg")
        except FileNotFoundError:
            raise Http404("Arquivo não encontrado.")
        resposta["Cache-Control"] = "private, max-age=3600"   # só no navegador do usuário
        resposta["X-Content-Type-Options"] = "nosniff"
        return resposta


class VipVeiculoPorPlaca(PermissionRequiredMixin, View):
    """Dados do veículo já cadastrado com esta placa (para preencher o formulário). Só consulta."""
    permission_required = f"{APP}.add_registrovip"

    def get(self, request):
        placa = normalizar_placa(request.GET.get("placa", ""))
        v = Veiculo.objects.filter(placa=placa).first() if placa else None
        if not v:
            return JsonResponse({"encontrado": False})
        chave = {c.label.lower(): c.value for c in Cor}.get((v.cor or "").strip().lower())
        return JsonResponse({
            "encontrado": True, "marca": v.marca, "modelo": v.modelo, "ano": v.ano, "chassi": v.chassi,
            "cor": chave or Cor.OUTRA, "cor_outra": "" if chave else v.cor,
        })

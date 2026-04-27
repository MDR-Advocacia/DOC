# Análise de Redesign — Projeto DOC alinhado ao padrão Flow

Documento técnico-visual que diagnostica a interface atual do DOC, define o novo design system (inspirado no DunaFlow/OneTask) e apresenta um plano de execução página por página, mantendo Bootstrap 5, o logo Duna e a base Django.

---

## 1. Resumo executivo

O DOC hoje funciona, mas a interface tem três problemas estruturais que impedem a percepção de "ferramenta premium":

1. **Navegação superior superpovoada.** São 8 links no topo (Dashboard, Gerador, Cálculo, Processos, Minha Biblioteca, Acervo, Histórico, FAQ) + dropdown administrativo com mais 4–5 ações. Em uma navbar horizontal isso vira um menu visualmente plano, sem hierarquia, e quebra mal abaixo de 1200px. O Flow já resolveu isso com sidebar lateral seccionada — é a primeira mudança a fazer.

2. **Identidade fragmentada.** Coexistem "DunaDoc", "DunaFlow", "Doc" e "Duna" em títulos, navbar e telas. O login usa um gradiente cyan/navy que não aparece em mais nenhum lugar do app. O Flow tem um wordmark único e um sistema de cores HSL coerente — vamos importar essa coerência.

3. **Tokens de design implícitos.** Cards têm `shadow-sm` aqui, `shadow-sm border-0` ali, `shadow-sm bg-white` em outro lugar. Botões pulam entre `btn-primary`, `btn-warning`, `btn-success`, `btn-info` sem critério semântico. Cores de gráfico são arbitrárias (#6610f2, #d63384, #fd7e14) e não respeitam a paleta da marca. Resultado: o app parece "montado" em vez de "desenhado". A solução é extrair tokens (cores, raios, sombras, espaçamentos) em variáveis CSS e usar apenas elas.

A boa notícia: a estrutura Django + Bootstrap 5 do DOC é totalmente compatível com o que precisamos. **Não vamos trocar de stack** — vamos sobrescrever Bootstrap com um design system custom expresso em CSS variables, replicando 1:1 a linguagem do Flow.

---

## 2. Diagnóstico do estado atual

### 2.1 Arquitetura de informação

A navbar atual tenta apresentar todas as funcionalidades no mesmo nível, mas elas pertencem a domínios distintos:

- **Geração de documentos:** Gerador (catálogo), Acervo Geral, Minha Biblioteca, FAQ
- **Operação processual:** Processos, Importação em lote
- **Análise jurídica:** Cálculo Cível
- **Histórico do usuário:** Documentos gerados
- **Administração:** Gestão de Usuários, Equipes, Disparo Administrativo, Monitoramento, Admin Django

Empilhar isso linearmente força o usuário a ler 8 rótulos toda vez que precisa navegar. O Flow agrupa por domínio e usa títulos de seção em uppercase pequeno como rótulos visuais — vamos copiar essa lógica.

### 2.2 Linguagem visual atual

| Elemento | Estado atual | Problema |
|---|---|---|
| Navbar | Gradient `#004ecb → #001233 → #02040a` | Cor competiu com o conteúdo, sem hierarquia entre links |
| Tipografia | Inter 300/400/500 + Montserrat 600/700/800 | Duas famílias, três pesos por família — mais caro de manter, sem ganho real |
| Paleta | Azul Duna `#2e5bf0` + dark navy `#0a0e27` + Bootstrap defaults | OK, mas não consistente: gráficos usam roxos/rosas/laranjas fora da paleta |
| Raio | Padrões Bootstrap (4px, 8px) + alguns 12px (login, alerts) | Inconsistente — Flow usa 16px (1rem) padrão |
| Sombra | `shadow-sm` no card padrão; `shadow-sm border-0`; algumas com `0 8px 16px rgba(0,0,0,.1)` no hover | Inconsistente — Flow tem token `--shadow-card` único |
| Botões | Sólido azul, sólido warning, sólido success, outline azul, outline secondary, btn-light border, btn-link | Falta hierarquia: qual é o botão primário visualmente? |
| Tabelas | `table table-hover` com `thead table-light` e padding `ps-4 pe-4` | OK, mas headers ficam em maiúsculas inline (`text-uppercase`) misturadas com normais |
| Status | Badges `bg-success-subtle text-success border` ou `bg-primary text-white` | Duas linguagens convivendo |
| Charts | Doughnut roxo/rosa/laranja + barras dark navy | Cores fora da paleta da marca |

### 2.3 Pontos fortes a preservar

- A semântica de campos do `formulario.html` (currency, cpf, dropdown, dependência condicional) é boa — só precisa de novas roupas.
- A organização do `guia.html` (sidebar de âncoras + accordion de seções) já antecipa o padrão de sidebar lateral.
- A paginação centralizada em `includes/pagination.html` facilita a refatoração.
- O sistema de favoritos com fetch otimista (`btn-favoritar`) é uma microinteração madura.

---

## 3. Design system "Flow para DOC"

Tokens extraídos do `index.css` do OneTask, traduzidos para o stack Bootstrap 5 do DOC.

### 3.1 Cores (HSL — variáveis CSS)

```css
:root {
  /* Marca */
  --duna-navy: 220 74% 14%;        /* #0A1940 */
  --duna-blue: 217 100% 56%;       /* #1E7BFF */
  --duna-blue-soft: 215 95% 72%;
  --duna-blue-tint: 217 100% 96%;  /* fundo de hover/badge sutil */

  /* Superfícies */
  --bg: 220 15% 97%;               /* fundo geral */
  --surface: 0 0% 100%;            /* cards/sidebar/modal */
  --surface-2: 220 20% 98%;        /* second-level surfaces */
  --border: 220 20% 90%;
  --border-strong: 220 15% 80%;

  /* Texto */
  --text: 220 74% 14%;             /* h1..h6, body */
  --text-muted: 220 15% 45%;
  --text-soft: 220 15% 60%;

  /* Status semânticos */
  --success: 140 70% 45%;
  --warning: 40 90% 50%;
  --error: 0 75% 55%;
  --info: 217 100% 56%;            /* = duna-blue */

  /* Sistema */
  --radius: 1rem;                  /* 16px — cards e modais */
  --radius-sm: .625rem;            /* 10px — botões, inputs */
  --shadow-card: 0 4px 20px hsl(220 25% 15% / .08);
  --shadow-elev: 0 8px 32px hsl(220 25% 15% / .12);
  --transition: all .25s cubic-bezier(.4,0,.2,1);
}
```

### 3.2 Tipografia

Uma família só: **Inter** (300/400/500/600/700). Aposenta o Montserrat — Inter 600/700 cobre tudo que Montserrat fazia sem o letter-spacing artificial.

```css
body { font-family: 'Inter', system-ui, sans-serif; font-weight: 400; }
h1, h2, h3, .h-display { font-weight: 700; letter-spacing: -.02em; }
h4, h5 { font-weight: 600; letter-spacing: -.01em; }
.eyebrow { font-size: .68rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: hsl(var(--text-muted)); }
```

Para o wordmark "Flow" (que vai aparecer no logo da sidebar), uma fonte secundária `Jura` carregada só nesse elemento.

### 3.3 Componentes-chave

**Card (substitui `.card.shadow-sm.border-0`)**
```css
.card-flow {
  background: hsl(var(--surface));
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  transition: var(--transition);
}
.card-flow:hover { box-shadow: var(--shadow-elev); }
```

**Botão primário (substitui `btn-primary`)**
```css
.btn-flow {
  background: hsl(var(--duna-blue));
  color: #fff;
  border-radius: var(--radius-sm);
  padding: .625rem 1.125rem;
  font-weight: 500;
  border: none;
  transition: var(--transition);
}
.btn-flow:hover { background: hsl(217 100% 50%); transform: translateY(-1px); box-shadow: 0 4px 14px hsl(var(--duna-blue) / .35); }
```

**Botão outline**
```css
.btn-flow-outline {
  background: transparent;
  border: 1px solid hsl(var(--border-strong));
  color: hsl(var(--text));
  border-radius: var(--radius-sm);
}
.btn-flow-outline:hover { background: hsl(var(--surface-2)); }
```

**KPI card (substitui os cards com `bg-primary text-white` da home)**

Card branco, número grande em navy, ícone em "tile" colorido translúcido no canto. Padrão idêntico ao `KpiCard` do `DashboardHome.tsx` do Flow.

```html
<div class="kpi">
  <div class="kpi-meta">
    <span class="eyebrow">Documentos gerados</span>
    <span class="kpi-value">1.284</span>
    <span class="kpi-caption">+12% vs. mês anterior</span>
  </div>
  <div class="kpi-tile kpi-tile--blue"><i class="fa-solid fa-rocket"></i></div>
</div>
```

```css
.kpi { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; padding:1.25rem; }
.kpi-value { font-size: 2rem; font-weight: 700; color: hsl(var(--duna-navy)); letter-spacing: -.02em; }
.kpi-caption { font-size: .75rem; color: hsl(var(--text-muted)); }
.kpi-tile { width: 44px; height: 44px; border-radius: 12px; display:flex; align-items:center; justify-content:center; }
.kpi-tile--blue { background: hsl(var(--duna-blue) / .08); color: hsl(var(--duna-blue)); }
.kpi-tile--success { background: hsl(var(--success) / .1); color: hsl(var(--success)); }
.kpi-tile--warning { background: hsl(var(--warning) / .12); color: hsl(35 90% 40%); }
.kpi-tile--error { background: hsl(var(--error) / .1); color: hsl(var(--error)); }
```

**Sidebar lateral (substitui a navbar superior)**

```html
<aside class="sb">
  <div class="sb-brand">
    <img src="logo-duna-colorida.png" alt="Duna" class="sb-logo">
    <span class="flow-mark">Flow</span>
  </div>

  <nav class="sb-nav">
    <a href="..." class="sb-item is-active"><i class="fa-solid fa-house"></i>Dashboard</a>

    <div class="sb-section">Geração de documentos</div>
    <a href="..." class="sb-item"><i class="fa-solid fa-file-pen"></i>Gerador</a>
    <a href="..." class="sb-item"><i class="fa-solid fa-bookmark"></i>Minha Biblioteca</a>
    <a href="..." class="sb-item"><i class="fa-solid fa-books"></i>Acervo Geral</a>

    <div class="sb-section">Operação</div>
    <a href="..." class="sb-item"><i class="fa-solid fa-folder-tree"></i>Processos</a>
    <a href="..." class="sb-item"><i class="fa-solid fa-scale-balanced"></i>Cálculo Cível</a>

    <div class="sb-section">Histórico</div>
    <a href="..." class="sb-item"><i class="fa-solid fa-clock-rotate-left"></i>Documentos gerados</a>
    <a href="..." class="sb-item"><i class="fa-solid fa-circle-question"></i>FAQ</a>
  </nav>
</aside>
```

```css
.sb { width: 260px; background: hsl(var(--surface)); border-right: 1px solid hsl(var(--border)); position: fixed; top: 0; left: 0; bottom: 0; padding: 1rem 0; }
.sb-brand { display:flex; align-items:center; gap:.5rem; padding: .25rem 1.25rem 1.25rem; border-bottom: 1px solid hsl(var(--border)); }
.sb-logo { height: 28px; width: auto; }
.flow-mark { font-family: 'Jura', 'Inter', sans-serif; font-weight: 500; font-size: 1.6rem; line-height: 1;
  background: linear-gradient(90deg, hsl(var(--duna-navy)), hsl(var(--duna-blue)));
  -webkit-background-clip: text; background-clip: text; color: transparent;
  filter: drop-shadow(0 0 4px hsl(var(--duna-blue) / .35));
}
.sb-nav { padding: 1rem .75rem; display:flex; flex-direction:column; gap:.125rem; }
.sb-section { font-size: .68rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: hsl(var(--text-soft)); padding: 1rem .75rem .35rem; }
.sb-item { display:flex; align-items:center; gap:.75rem; padding:.5rem .75rem; border-radius: var(--radius-sm); color: hsl(var(--text-muted)); text-decoration: none; font-size: .9rem; font-weight: 500; transition: var(--transition); }
.sb-item i { width: 16px; text-align: center; }
.sb-item:hover { background: hsl(var(--surface-2)); color: hsl(var(--duna-blue)); }
.sb-item.is-active { background: hsl(var(--duna-blue-tint)); color: hsl(var(--duna-blue)); }
```

A área de admin (que hoje fica no dropdown) vai aparecer condicionalmente como a quinta seção da sidebar para `user.is_staff`.

**Header sticky (substitui a navbar)**

```html
<header class="topbar">
  <button class="topbar-toggle d-lg-none"><i class="fa-solid fa-bars"></i></button>
  <div class="topbar-search">
    <i class="fa-solid fa-magnifying-glass"></i>
    <input placeholder="Buscar modelos, processos, cálculos…">
  </div>
  <div class="topbar-actions">
    <button class="topbar-icon" title="Notificações"><i class="fa-regular fa-bell"></i></button>
    <button class="topbar-user">
      <i class="fa-solid fa-circle-user"></i>
      <span>{{ user.first_name }}</span>
    </button>
  </div>
</header>
```

Header com 60px de altura, fundo branco, borda inferior 1px, busca global com placeholder cinza, dropdown do usuário ancorado à direita.

**Tabela**

Manter Bootstrap `table` mas: `thead` sem fundo (só borda inferior 1px), `th` em eyebrow style, hover suave de linha, sem zebra default.

```css
.table-flow thead th { background: transparent; border-bottom: 1px solid hsl(var(--border)); color: hsl(var(--text-muted)); font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; font-weight: 600; padding: .9rem 1rem; }
.table-flow tbody td { padding: .9rem 1rem; border-color: hsl(var(--border)); font-size: .9rem; vertical-align: middle; }
.table-flow tbody tr { transition: var(--transition); }
.table-flow tbody tr:hover { background: hsl(var(--surface-2)); }
```

**Badge de status**

Sistema único com 5 tons (`info`, `success`, `warning`, `error`, `neutral`), todos em padrão tint-suave + texto saturado, idêntico ao Flow.

```css
.chip { display:inline-flex; align-items:center; gap:.4rem; font-size: .72rem; font-weight: 600; padding: .25rem .6rem; border-radius: 999px; line-height:1; }
.chip--info { background: hsl(var(--duna-blue) / .1); color: hsl(var(--duna-blue)); }
.chip--success { background: hsl(var(--success) / .12); color: hsl(140 70% 30%); }
.chip--warning { background: hsl(var(--warning) / .14); color: hsl(35 90% 35%); }
.chip--error { background: hsl(var(--error) / .12); color: hsl(0 70% 40%); }
.chip--neutral { background: hsl(var(--surface-2)); color: hsl(var(--text-muted)); border: 1px solid hsl(var(--border)); }
```

**Inputs**

```css
.input-flow, .form-control, .form-select {
  background: hsl(var(--surface));
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius-sm);
  padding: .625rem .85rem;
  font-size: .9rem;
  transition: var(--transition);
}
.input-flow:focus, .form-control:focus, .form-select:focus {
  border-color: hsl(var(--duna-blue));
  box-shadow: 0 0 0 3px hsl(var(--duna-blue) / .15);
  outline: none;
}
```

### 3.4 Fundo com marca-d'água

Replicar o efeito do Flow: o logotipo Duna fica fixo no centro da viewport com `opacity: .04`, dando textura sutil sem atrapalhar leitura.

```css
body::before {
  content: "";
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background: url('/static/img/logo-duna-colorida.png') center/min(640px,60vmin) no-repeat;
  opacity: .04;
}
.app-shell { position: relative; z-index: 1; }
```

---

## 4. Arquitetura visual proposta — layout shell

```
┌─────────────────────────────────────────────────────────────────┐
│ [Logo Duna │ Flow]                                              │
│                                                                 │
│  Dashboard                                                      │
│                                                                 │
│  GERAÇÃO DE DOCUMENTOS    │  ┌───────────────────────────────┐  │
│  ▶ Gerador                │  │ Topbar (busca, sino, perfil)  │  │
│    Minha Biblioteca       │  ├───────────────────────────────┤  │
│    Acervo Geral           │  │                               │  │
│                           │  │   Conteúdo da página atual    │  │
│  OPERAÇÃO                 │  │                               │  │
│    Processos              │  │                               │  │
│    Cálculo Cível          │  │                               │  │
│                           │  │                               │  │
│  HISTÓRICO                │  │                               │  │
│    Documentos gerados     │  │                               │  │
│    FAQ                    │  │                               │  │
│                           │  │                               │  │
│  ADMINISTRAÇÃO  (staff)   │  │                               │  │
│    Usuários                │  │                               │  │
│    Equipes                 │  │                               │  │
│    Disparo                 │  │                               │  │
│    Monitoramento           │  │                               │  │
│  ─────────────             │  │                               │  │
│  © 2026 Duna.Tech          │  └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
   260px sidebar fixa            main-content (overflow-auto)
```

Em <992px: sidebar vira off-canvas (`d-lg-none` + Bootstrap Offcanvas), botão hambúrguer no topbar.

---

## 5. Plano de migração página por página

Estratégia: introduzir o novo design system em **camadas**, não em uma reescrita big-bang.

### Fase 1 — Fundação (1 dia)

**Objetivo:** colocar o esqueleto Flow no ar com zero quebra funcional.

1. Criar `docgen/static/css/flow.css` com:
   - Variáveis HSL (Seção 3.1)
   - Reset/sobrescritas Bootstrap (`.btn-primary`, `.card`, `.form-control`, `.table`, `.badge`, `.alert`)
   - Componentes novos (`.sb-*`, `.kpi-*`, `.chip--*`, `.flow-mark`, `.eyebrow`)
   - Marca-d'água
2. Refatorar `docgen/templates/base.html`:
   - Trocar navbar superior por sidebar lateral + topbar
   - Carregar Inter (300-700) e Jura (500) do Google Fonts; remover Montserrat
   - Manter Bootstrap 5 + Font Awesome (compatibilidade total)
   - Estrutura `app-shell > .sb + .main > .topbar + main`
   - Footer compacto, dentro do `.main` (não fixo)
3. Padronizar mensagens (`messages` framework) com novo visual de toast no canto inferior-direito.

**Critério de pronto:** todas as páginas continuam carregando e navegando, mas com sidebar nova e fundo Flow.

### Fase 2 — Identidade do login (meio dia)

`registration/login.html`, `signup.html`, `definir_primeira_senha.html`:

- Remover gradiente cyan/navy.
- Tela centralizada com card branco `var(--radius)`, fundo Flow padrão.
- Logo Duna 64px + wordmark "Flow" em neon (animação `flow-neon-pulse` opcional, com `prefers-reduced-motion` desativando).
- Subtítulo "by MDR Advocacia" em eyebrow.
- Inputs novos, botão "Entrar" full-width primário.
- Texto "Solicitar acesso" em link discreto abaixo.

### Fase 3 — Dashboard (1 dia)

`docgen/home.html`:

- Header da página: H1 "Dashboard" + caption "Visão geral do escritório."
- Linha de 4 KPIs: Documentos gerados / Modelos disponíveis / Processos em captura / Cálculos do mês. Tile colorido por contexto (azul, navy, warning, success).
- Linha 2/3 + 1/3:
  - **Velocidade de produção** (área chart Chart.js, dois datasets: Gerados vs Modelos novos, gradiente azul)
  - **Distribuição por setor** (donut com paleta única `--duna-blue → --duna-blue-soft → --duna-navy → --text-muted`)
- Banner "Ações rápidas" com 4 chips-botão (Novo documento, Novo cálculo, Importar processos, Disparo administrativo).
- Banner staff de "Disparo administrativo" com ícone+CTA.

### Fase 4 — Catálogo + Bibliotecas (1 dia)

`docgen/lista.html` (Catálogo):

- Toolbar acima do grid: busca expansiva + selects de Setor/Área/Categoria como `.input-flow`.
- Grid 3 colunas (lg) / 2 (md) / 1 (sm).
- Card de modelo redesenhado:
  - Topo: chip do setor (cor por categoria), estrela de favoritar à direita.
  - Título em peso 600.
  - Descrição muted, 2 linhas com `-webkit-line-clamp`.
  - Footer: botão "Preencher" + ícone de configuração para staff.
  - Hover: `transform: translateY(-2px)` + `var(--shadow-elev)`.

`docgen/biblioteca.html` (Acervo):

- Mesma toolbar.
- Tabela `.table-flow` com Título / Setor + Área (chips) / Data / Ação.

`docgen/minha_biblioteca.html`:

- Coluna esquerda 280px: lista de pastas no estilo `.sb-item` (mesmo vocabulário da sidebar principal, criando coerência).
- Botão "+ Nova pasta" no topo da coluna como `.btn-flow-outline`.
- Coluna direita: grid 2 colunas de cards iguais ao catálogo.
- Modal "Nova pasta" e "Compartilhar" com `var(--radius)` e header limpo (sem fundo).

### Fase 5 — Formulário de geração (meio dia)

`docgen/formulario.html`:

- Coluna central 720px max-width.
- Header da página: breadcrumb "Catálogo › {{ setor }}" + título do template.
- Card único agrupando todos os campos.
- Cada campo:
  - Label em peso 500 + asterisco vermelho se required
  - Input `.input-flow`
  - Helper text muted abaixo
  - Campos condicionais com indentação visual + barra azul à esquerda em `border-left: 3px solid hsl(var(--duna-blue) / .3)`
- Footer sticky no final do card com "Cancelar" + "Gerar documento" (primário).

### Fase 6 — Processos + Cálculo (1 dia)

`docgen/processos_lista.html`, `calculadora/lista.html`:

- Toolbar de filtros em card colapsável (`details/summary` ou Bootstrap collapse).
- Tabela `.table-flow`.
- Status como `.chip--*` com mapping:
  - `pendente` → warning
  - `em_processamento` → info
  - `concluido` → success
  - `erro` → error
  - `cancelado` → neutral

`processo_detalhe.html`, `calculadora/detalhe.html`:

- Header com chip de status + título + botões de ação à direita.
- Painel de propriedades à esquerda, painel de eventos/timeline à direita.

### Fase 7 — Áreas administrativas (meio dia)

`gerenciar_usuarios.html`, `gerenciar_equipes.html`, `gerenciar_membros.html`, `processos_monitoramento.html`, `disparo_obrigacao_fazer.html`, `processos_importar_lote.html`:

- Mesma toolbar + tabela. Padrão.
- Modais de criação/edição com `var(--radius)`, header limpo.
- Disparo administrativo: stepper visual (Upload planilha → Mapear colunas → Preview → Disparar).

### Fase 8 — FAQ + páginas auxiliares (meio dia)

`docgen/guia.html`:

- Sidebar de âncoras já existe; estilizar como `.sb` interna.
- Cards de seção colapsáveis com header limpo e ícone de chevron animado.
- Bloco de código com fundo `var(--surface-2)` e `border-radius: var(--radius-sm)`.

### Fase 9 — Polimento (meio dia)

- Toasts/messages no canto inferior-direito, animação fade-in-up.
- Skeleton loaders nos cards e tabelas durante fetches AJAX.
- Estados vazios: ilustração simples em SVG (linhas, sem cor) + título + caption + CTA.
- Acessibilidade: `aria-label` nos botões só com ícone, contraste em "muted" auditado, `:focus-visible` ring azul em todos os interativos.
- Suporte opcional a dark mode (HSL facilita: já temos as variáveis).

---

## 6. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Bootstrap-utility classes nos templates conflitarem com novo CSS | Sobrescrever apenas `.btn`, `.card`, `.form-control`, `.table`, `.badge`, `.alert`, `.modal-content`. Não tocar em utilities (`.text-*`, `.d-*`, `.p-*`). |
| Charts atuais (Chart.js) com cores hard-coded | Substituir array de cores por variáveis JS lidas de `getComputedStyle(document.documentElement)` no início do `extra_js` da home. |
| Templates de e-mail (disparo) podem usar mesmo CSS | Migração de e-mail é fora deste escopo — manter inline-styles separados. |
| Compatibilidade IE/Edge antigo | Variáveis CSS com HSL têm 100% de suporte em browsers em uso. Gradient `-webkit-background-clip` para wordmark exige Safari 9+/Chrome 26+ — OK. |
| Sidebar fixa em monitores 1366×768 | 260px de sidebar deixa 1106px de main, suficiente para dashboards. Em <992px vira off-canvas. |
| Quebrar fluxos em produção | Cada fase é uma PR isolada e reversível. Merge gradual, com fallback do `base.html` antigo guardado em `base_legacy.html` por 2 semanas. |

---

## 7. Próximos passos sugeridos

1. **Hoje:** revisar este documento + validar o mockup HTML (`MOCKUP-FLOW.html`) que criei junto.
2. **Aprovação dos tokens** (Seção 3.1): confirmar paleta, raios, sombras.
3. **Decidir sobre o nome do produto:** unificar para "Duna Flow" ou manter "Doc / DunaDoc"? Vou usar "Flow" como wordmark visual por padrão; o nome técnico fica a seu critério.
4. **Implementação faseada:** começar pela Fase 1 (base + flow.css) — entrega visível em 1 dia.
5. **Critério de aceite por fase:** screenshots antes/depois de cada PR.

---

## 8. Apêndice A — Inventário de templates afetados

| Template | Linhas | Fase |
|---|---|---|
| `docgen/templates/base.html` | 190 | 1 |
| `docgen/templates/registration/login.html` | 170 | 2 |
| `docgen/templates/registration/signup.html` | 23 | 2 |
| `docgen/templates/registration/definir_primeira_senha.html` | 42 | 2 |
| `docgen/templates/docgen/home.html` | 186 | 3 |
| `docgen/templates/docgen/lista.html` | 188 | 4 |
| `docgen/templates/docgen/biblioteca.html` | 118 | 4 |
| `docgen/templates/docgen/minha_biblioteca.html` | 297 | 4 |
| `docgen/templates/docgen/formulario.html` | 147 | 5 |
| `docgen/templates/docgen/configurar_template.html` | 135 | 5 |
| `docgen/templates/docgen/novo_template.html` | 80 | 5 |
| `docgen/templates/docgen/dashboard.html` | 55 | 5 |
| `docgen/templates/docgen/processos_lista.html` | 123 | 6 |
| `docgen/templates/docgen/processo_detalhe.html` | 137 | 6 |
| `docgen/templates/docgen/processos_monitoramento.html` | 133 | 7 |
| `docgen/templates/docgen/processos_importar_lote.html` | 88 | 7 |
| `docgen/templates/docgen/disparo_obrigacao_fazer.html` | 170 | 7 |
| `docgen/templates/docgen/gerenciar_usuarios.html` | 85 | 7 |
| `docgen/templates/docgen/gerenciar_equipes.html` | 255 | 7 |
| `docgen/templates/docgen/gerenciar_membros.html` | 218 | 7 |
| `docgen/templates/docgen/guia.html` | 305 | 8 |
| `calculadora/templates/calculadora/lista.html` | 77 | 6 |
| `calculadora/templates/calculadora/novo.html` | 63 | 6 |
| `calculadora/templates/calculadora/detalhe.html` | 176 | 6 |

Total: 24 templates, 3.461 linhas. Estimativa de esforço total: 5–6 dias de trabalho focado.

## 9. Apêndice B — Tabela de tradução de classes Bootstrap → Flow

| Atual | Equivalente Flow |
|---|---|
| `card border-0 shadow-sm` | `card-flow` (ou só `card` com sobrescrita) |
| `btn btn-primary` | `btn btn-flow` ou manter `btn-primary` (sobrescrito no flow.css) |
| `btn btn-outline-secondary` | `btn btn-flow-outline` |
| `badge bg-primary` | `chip chip--info` |
| `badge bg-success-subtle text-success` | `chip chip--success` |
| `badge bg-warning text-dark` | `chip chip--warning` |
| `table table-hover` | `table table-flow` |
| `thead table-light` | `thead` (sem classe) |
| `form-control bg-light` | `form-control` (estilo padrão Flow já usa surface-2) |
| `text-uppercase fw-bold small text-secondary` | classe `eyebrow` |
| `shadow-sm` em cards | remover (já está em `.card`) |

Esta tabela serve como guia de busca-e-substituição quando for migrar cada template.

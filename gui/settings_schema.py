"""What the control panel shows: menu sections, the tasks in each one, their
per-account options, the planning panels and the "How to" guide.

Field keys are the per-account preference keys the tasks read
(memory/accounts/<id>.json -> "preferences"). Every user-facing text is an
(English, Portuguese) pair resolved per request by gui.i18n.localize. How-to
blocks are rendered as plain text by the UI (never as HTML).
"""
from __future__ import annotations

import config
from gui.i18n import L


# -- how-to blocks ------------------------------------------------------------
def p(en: str, pt: str) -> dict:
    return {"type": "p", "text": L(en, pt)}


def h(en: str, pt: str) -> dict:
    return {"type": "h", "text": L(en, pt)}


def steps(*items: tuple[str, str]) -> dict:
    return {"type": "steps", "items": [L(*item) for item in items]}


def bullets(*items: tuple[str, str]) -> dict:
    return {"type": "list", "items": [L(*item) for item in items]}


def tip(en: str, pt: str) -> dict:
    return {"type": "tip", "text": L(en, pt)}


def warn(en: str, pt: str) -> dict:
    return {"type": "warn", "text": L(en, pt)}


NO_OPTIONS = p("There are no options besides the task's ON/OFF switch.",
               "Não há opções além da chave ON/OFF da tarefa.")
SWITCH_ON = ("Set the task switch (next to the title) to ON.",
             "Deixe a chave da tarefa (ao lado do título) em ON.")


# -- fields ---------------------------------------------------------------------
def _text(pair):
    return L(*pair) if pair else None


def int_field(key, label, lo, hi, default, help=None, group=None) -> dict:
    return {"key": key, "label": _text(label), "type": "int", "min": lo, "max": hi,
            "default": default, "help": _text(help), "group": group}


def bool_field(key, label, default, help=None, group=None) -> dict:
    return {"key": key, "label": _text(label), "type": "bool", "default": default,
            "help": _text(help), "group": group}


def choice_field(key, label, choices, default, help=None) -> dict:
    return {"key": key, "label": _text(label), "type": "choice",
            "choices": [{"value": v, "label": _text(text)} for v, text in choices],
            "default": default, "help": _text(help), "group": None}


def _gather_fields() -> list[dict]:
    names = {"iron": ("Iron", "Ferro", "Seth"), "stone": ("Stone", "Pedra", "Edwin"),
             "wood": ("Wood", "Madeira", "Forrest"), "bread": ("Bread", "Pão", "Olive")}
    fields = []
    for resource in config.GATHER_RESOURCE_ORDER:
        en, pt, hero = names[resource]
        group = {"id": resource, "label": L(en, pt),
                 "hint": L(f"Gatherer hero: {hero}", f"Herói coletor: {hero}")}
        fields.append(bool_field(f"gather_{resource}_enabled", ("Gather", "Coletar"), True, group=group))
        fields.append(int_field(f"gather_{resource}_level", ("Max level", "Nível máximo"),
                                config.GATHER_LEVEL_MIN, config.GATHER_LEVEL_MAX,
                                config.GATHER_LEVEL_START, group=group))
    return fields


GENERAL_HOWTO = [
    p("The panel controls one bot per emulator. Each bot identifies the logged-in account "
      "(by reading the governor profile) and applies the options saved for THAT account.",
      "O painel controla um bot por emulador. Cada bot identifica a conta logada "
      "(lendo o perfil do governador) e aplica as opções salvas para ESSA conta."),
    steps(
        ("In BlueStacks, enable ADB under Settings → Advanced → Android Debug Bridge and note "
         "the port (e.g. 127.0.0.1:5555).",
         "No BlueStacks, ative o ADB em Configurações → Avançado → Android Debug Bridge "
         "e anote a porta (ex.: 127.0.0.1:5555)."),
        ("Click \"Find emulators\". If yours doesn't show up, type the port in \"Manual ADB "
         "port\" and click \"Add\".",
         "Clique em \"Procurar emuladores\". Se o seu não aparecer, digite a porta em "
         "\"Porta ADB manual\" e clique em \"Adicionar\"."),
        ("Pick the account in the selector at the top and adjust each menu (Resources, Hunt, "
         "Alliance...). Everything is saved automatically when you change a field.",
         "Escolha a conta no seletor do topo e ajuste cada menu (Coleta, Caça, Aliança...). "
         "Tudo é salvo automaticamente ao alterar um campo."),
        ("Click \"Start\" on the emulator. The log shows up right below.",
         "Clique em \"Iniciar\" no emulador. O log aparece logo abaixo."),
        ("While the bot runs: \"Pause\" freezes it before its next action (tap, search, "
         "screenshot) and \"Resume\" continues exactly where it stopped. \"Stop\" ends the bot.",
         "Com o bot rodando: \"Pausar\" congela o bot antes da próxima ação (toque, busca, "
         "captura de tela) e \"Retomar\" continua exatamente de onde parou. \"Parar\" encerra o bot."),
        ("Closing the panel also stops every bot it started.",
         "Fechar o painel também encerra todos os bots que ele iniciou."),
    ),
    tip("Use \"Pause\" when you want to play manually for a few minutes without losing the "
        "tasks' state. On resume, if the screen changed and the running task fails, the bot "
        "goes back to the city and tries again.",
        "Use \"Pausar\" quando quiser jogar manualmente por alguns minutos sem perder o "
        "estado das tarefas. Ao retomar, se a tela mudou e a tarefa em andamento falhar, o bot "
        "volta para a cidade e tenta de novo."),
    tip("The account shows up in the selector by itself after the bot's first run. To set it "
        "up earlier, use \"+ Account\" and enter the ID shown on the governor profile in the "
        "game (e.g. 256466296).",
        "A conta aparece sozinha no seletor depois da primeira execução do bot. Para "
        "configurar antes, use \"+ Conta\" e informe o ID que aparece no perfil do "
        "governador no jogo (ex.: 256466296)."),
    tip("Changes apply while the bot runs: switching a task ON/OFF takes effect on the next "
        "cycle (a task already running finishes first) and levels/options are re-read before "
        "each run of the task.",
        "As mudanças valem com o bot rodando: colocar uma tarefa em ON/OFF é aplicado no "
        "próximo ciclo (uma tarefa já em andamento termina antes) e níveis/opções são "
        "relidos antes de cada execução da tarefa."),
    warn("An account with no known ID (profile not read) runs ALL tasks with the default values.",
         "Uma conta sem ID conhecido (perfil não lido) roda TODAS as tarefas com os "
         "valores padrão."),
]


# -- planning panels (rendered by gui/static/planning.js, data in gui/planning.py) --
PANEL_PROFILE = {
    "id": "profile",
    "title": L("Planning profile", "Perfil do planejamento"),
    "summary": L("Account data used by the Events and Troops calculations.",
                 "Dados da conta usados nos cálculos de Eventos e Tropas."),
    "howto": [
        p("Values that YOU enter for planning. The selector at the top shows the profile the "
          "bot reads from the game; the bot never changes this block.",
          "Valores que VOCÊ informa para o planejamento. O seletor do topo mostra o perfil que o "
          "bot lê do jogo; este bloco não é alterado pelo bot."),
        steps(
            ("Fill in Governor, VIP, Current kingdom and Power (reference only).",
             "Preencha Governador, VIP, Reino atual e Poder (só para referência)."),
            ("In \"March queues\" pick how many queues you have unlocked (1–6). This number sets "
             "how many teams fit in each event: Swordland uses one team per queue and Bear Hunt "
             "accepts the queues + 1 own rally.",
             "Em \"Filas de marcha\" escolha quantas filas você tem desbloqueadas (1–6). Esse número "
             "define quantos times cabem em cada evento: o Swordland usa um time por fila e o Bear "
             "Hunt aceita as filas + 1 rally próprio."),
        ),
        tip("Everything is saved automatically when you leave the field. One backup per day is "
            "kept in memory/planning/backups.",
            "Tudo é salvo automaticamente ao sair do campo. Uma cópia de segurança por dia fica em "
            "memory/planning/backups."),
    ],
}

PANEL_HEROES = {
    "id": "heroes",
    "title": L("Heroes and gear", "Heróis e equipamentos"),
    "summary": L("Progress, stars, shards, portable gear and exclusive weapon of each hero.",
                 "Progresso, estrelas, shards, equipamento portátil e arma exclusiva de cada herói."),
    "howto": [
        p("Click a hero's name to open the details. \"Expand all\" / \"Collapse all\" open or "
          "close every hero at once.",
          "Clique no nome do herói para abrir os detalhes. \"Expandir todos\" / \"Recolher todos\" "
          "abrem ou fecham todos de uma vez."),
        h("Fields", "Campos"),
        bullets(
            ("Progress: level (1–80), stars (1–5), skill level (1–5) and whether they are maxed.",
             "Progresso: nível (1–80), estrelas (1–5), nível das habilidades (1–5) e se estão no máximo."),
            ("Stars and shards: enter this hero's shards in stock and how many of the 6 parts of "
             "the next star are done. The panel calculates how many shards are missing for the "
             "next part and to reach 5 stars.",
             "Estrelas e shards: informe os shards desse herói no estoque e quantos dos 6 pedaços da "
             "próxima estrela já estão completos. O painel calcula quantos shards faltam para o "
             "próximo pedaço e para chegar em 5 estrelas."),
            ("Gear: rarity, level and mastery of each piece (helmet, gloves, armor, boots).",
             "Equipamento: raridade, nível e maestria de cada peça (capacete, luvas, armadura, botas)."),
            ("Exclusive weapon: widget level. It belongs to the hero forever and never changes owner.",
             "Arma exclusiva: nível do widget. Ela é permanente do herói e nunca muda de dono."),
        ),
        h("Moving gear", "Mover equipamento"),
        steps(
            ("On the piece, click \"Move to another hero\".",
             "Na peça, clique em \"Mover para outro herói\"."),
            ("Pick the target hero (only heroes of the SAME class are listed) and confirm.",
             "Escolha o herói de destino (só aparecem heróis da MESMA classe) e confirme."),
            ("The piece keeps its level and mastery; the source hero is left without it.",
             "A peça vai com nível e maestria; o herói de origem fica sem ela."),
        ),
        warn("If the target already has a developed piece in that slot, it is REPLACED in the "
             "plan. In the game, unequip it first so you don't lose it.",
             "Se o destino já tiver uma peça desenvolvida nesse espaço, ela é SUBSTITUÍDA no "
             "planejamento. No jogo, desequipe antes para não perder."),
    ],
}

PANEL_HERO_PLAN = {
    "id": "hero_plan",
    "title": L("Hero plan", "Plano de heróis"),
    "summary": L("Ranking by class, gear transition and investment roadmap by generation.",
                 "Ranking por classe, troca de equipamento e roteiro de investimento por geração."),
    "howto": [
        p("Read-only block from your saved plan: the ranking sets the order used to fill several "
          "queues (best to worst), the gear transition explains how to pass the pieces to a new "
          "hero and the roadmap shows who to invest in each generation.",
          "Bloco informativo vindo do seu planejamento salvo: o ranking define a ordem usada para "
          "preencher várias filas (do melhor ao pior), a troca de equipamento explica como passar "
          "as peças para um herói novo e o roteiro mostra em quem investir a cada geração."),
    ],
}

PANEL_RESOURCE_STOCK = {
    "id": "resource_stock",
    "title": L("Resource and material stock", "Estoque de recursos e materiais"),
    "summary": L("Current amounts and a per-day consumption calculator for events.",
                 "Quantidades atuais e calculadora de consumo por dia de evento."),
    "howto": [
        steps(
            ("Update the current amount of each item (resources, governor gear and charm "
             "materials, skill books, keys and widget chests).",
             "Atualize as quantidades atuais de cada item (recursos, materiais de equipamento do "
             "governador e de amuletos, livros de habilidade, chaves e baús de widget)."),
            ("To check whether a resource lasts through an event, click \"Track usage\" on the "
             "item and use \"+ day\" to record each day's spending.",
             "Para saber se um recurso aguenta um evento, clique em \"Rastrear consumo\" no item e "
             "use \"+ dia\" para registrar o gasto de cada dia."),
            ("The table shows the remaining balance, the average spent per day and how many days "
             "the stock still lasts.",
             "A tabela mostra o saldo restante, a média gasta por dia e quantos dias o estoque ainda dura."),
        ),
        warn("The per-day usage tracking is not saved: it is gone when you close the panel. The "
             "amounts are saved.",
             "O rastreio de consumo por dia não é salvo: some ao fechar o painel. As quantidades, sim."),
    ],
}

PANEL_TROOP_STOCK = {
    "id": "troop_stock",
    "title": L("Troop stock", "Estoque de tropas"),
    "summary": L("Troops by type and level. Used to check the Events teams.",
                 "Tropas por tipo e nível. Usado para conferir os times de Eventos."),
    "howto": [
        steps(
            ("Enter how many troops you have of each level for Infantry, Cavalry and Archers.",
             "Informe quantas tropas você tem de cada nível em Infantaria, Cavalaria e Arqueiros."),
            ("Each type's total is calculated automatically and the update date changes to today.",
             "O total de cada tipo é calculado sozinho e a data de atualização muda para hoje."),
        ),
        tip("In Events, each event's summary compares the assigned troops with this stock and "
            "turns red when it exceeds what you have.",
            "Em Eventos, o resumo de cada evento compara as tropas escaladas com este estoque e "
            "fica vermelho quando passa do que você tem."),
    ],
}

PANEL_TROOP_PLAN = {
    "id": "troop_plan",
    "title": L("Troop development plan", "Plano de desenvolvimento de tropas"),
    "summary": L("Recommended training ratio and targets by type.",
                 "Proporção recomendada de treino e metas por tipo."),
    "howto": [
        p("The ratio comes from adding up the troops needed to fill every planned event. Use it "
          "to decide which type to train next.",
          "A proporção vem da soma das tropas necessárias para lotar todos os eventos planejados. "
          "Use-a para decidir qual tipo treinar a seguir."),
        bullets(
            ("\"Current\" comes from the Troop stock above (live).",
             "\"Atual\" vem do Estoque de tropas acima (ao vivo)."),
            ("\"Target\" can be adjusted; \"Missing\" = target − current.",
             "\"Meta\" pode ser ajustada; \"Falta\" = meta − atual."),
            ("Priority 1 is the type the events are missing the most.",
             "Prioridade 1 é o tipo que mais falta para os eventos."),
        ),
        tip("To train automatically, set the tier in the \"Train troops\" task above.",
            "Para treinar automaticamente, ajuste o tier na tarefa \"Treinar tropas\" acima."),
    ],
}

PANEL_EVENTS = {
    "id": "events",
    "title": L("Team distribution per event", "Distribuição dos times por evento"),
    "summary": L("Heroes and troops of each queue/group in Arena, King's Castle, Swordland, "
                 "Tri-Alliance and Bear Hunt.",
                 "Heróis e tropas de cada fila/grupo em Arena, Castelo do Rei, Swordland, "
                 "Tri-Alliance e Bear Hunt."),
    "howto": [
        h("Building the teams", "Montar os times"),
        steps(
            ("In each queue/group pick 1 Infantry, 1 Cavalry and 1 Archer hero. Heroes already "
             "assigned to another queue of the SAME event show as \"(in use)\" and are locked.",
             "Em cada fila/grupo escolha 1 herói de Infantaria, 1 de Cavalaria e 1 de Arqueiro. "
             "Heróis já escalados em outra fila do MESMO evento aparecem como \"(em uso)\" e ficam "
             "bloqueados."),
            ("Set the event's \"Troop cap per march\".",
             "Ajuste o \"Limite de tropas por marcha\" do evento."),
            ("On the Troops row, enter the % or the amount of each type: one field updates the "
             "other based on the cap.",
             "Na linha Tropas, informe a % ou a quantidade de cada tipo: um campo atualiza o outro "
             "com base no limite."),
            ("Check the summary at the end of the event: assigned total / stock (from Troops). "
             "Red = not enough troops.",
             "Confira o resumo no fim do evento: total escalado / estoque (de Tropas). Vermelho = "
             "falta tropa."),
        ),
        h("Event rules", "Regras de cada evento"),
        bullets(
            ("Arena: 5 heroes, classes may repeat.", "Arena: 5 heróis, pode repetir classe."),
            ("King's Castle: as LEADER, your whole trio applies to the entire rally; as JOINER, "
             "only the ability of the hero in position 1 counts toward the rally bonus.",
             "Castelo do Rei: como LÍDER, seu trio inteiro vale para o rally todo; como JOINER, só a "
             "habilidade do herói na posição 1 entra no bônus do rally."),
            ("Swordland: one team per march queue (the number of queues comes from the Profile "
             "in Account).",
             "Swordland: um time por fila de marcha (número de filas vem do Perfil em Conta)."),
            ("Bear Hunt: up to queues + 1 groups (the own rally doesn't use a queue); the troop "
             "cap per group is set by the kingdom.",
             "Bear Hunt: até filas + 1 grupos (o rally próprio não ocupa fila); o limite de tropas "
             "por grupo é definido pelo reino."),
        ),
        tip("Each event has a \"Why this team?\" with the reasoning saved in the plan.",
            "Cada evento tem um \"Por que este time?\" com a justificativa salva no planejamento."),
    ],
}


SECTIONS = [
    {
        "id": "account",
        "title": L("Account", "Conta"),
        "tasks": [],
        "panels": [PANEL_PROFILE, PANEL_HEROES, PANEL_HERO_PLAN],
    },
    {
        "id": "resources",
        "title": L("Resource gathering", "Coleta de recursos"),
        "tasks": [
            {
                "task": "Gather Resources",
                "title": L("Gather resources on the map", "Coletar recursos no mapa"),
                "summary": L("Keeps one active gather per resource, always with the right gatherer hero.",
                             "Mantém uma coleta ativa por recurso, sempre com o herói coletor certo."),
                "fields": _gather_fields(),
                "howto": [
                    p("The bot opens the world map search, picks the resource, looks for a node and "
                      "sends ONE march per resource with the specialist hero (Seth on iron, Edwin on "
                      "stone, Forrest on wood, Olive on bread) to get the gathering bonus. The other "
                      "two heroes of the formation are removed.",
                      "O bot abre a busca do mapa-múndi, escolhe o recurso, procura um nó e "
                      "envia UMA marcha por recurso com o herói especialista (Seth no ferro, "
                      "Edwin na pedra, Forrest na madeira, Olive no pão) para ganhar o bônus "
                      "de coleta. Os outros dois heróis da formação são removidos."),
                    h("How to set it up", "Como ajustar"),
                    steps(
                        SWITCH_ON,
                        ("For each resource, set \"Gather\" to ON to include it or OFF to skip it. "
                         "The sending order is always Iron → Stone → Wood → Bread.",
                         "Em cada recurso, deixe \"Coletar\" em ON para incluí-lo ou em OFF para "
                         "ignorá-lo. A ordem de envio é sempre Ferro → Pedra → Madeira → Pão."),
                        (f"In \"Max level\" ({config.GATHER_LEVEL_MIN}–{config.GATHER_LEVEL_MAX}) pick "
                         "the highest level the bot should look for. It starts at that level and drops "
                         "1 level at a time when: (a) there is no node of that level on the map, or "
                         "(b) your troops can't fill the node's capacity.",
                         f"Em \"Nível máximo\" ({config.GATHER_LEVEL_MIN}–{config.GATHER_LEVEL_MAX}) "
                         "escolha o nível mais alto que o bot deve procurar. Ele começa nesse "
                         "nível e desce 1 nível por vez quando: (a) não existe nó desse nível no "
                         "mapa, ou (b) suas tropas não conseguem encher a capacidade do nó."),
                    ),
                    h("How it decides", "Como ele decide"),
                    bullets(
                        ("It needs a free march queue. If all are busy, it checks again in 1 h.",
                         "Precisa de fila de marcha livre. Se todas estiverem ocupadas, reverifica em 1 h."),
                        ("If the specialist hero is already out on a march, that resource is already "
                         "being gathered and is skipped. The bot NEVER sends a gather without the specialist.",
                         "Se o herói especialista já está fora numa marcha, aquele recurso já está "
                         "sendo coletado e é pulado. O bot NUNCA envia coleta sem o especialista."),
                        ("With any gather active it checks again every 1 h; with none, every 20 min.",
                         "Com alguma coleta ativa, reverifica a cada 1 h; sem nenhuma, a cada 20 min."),
                        ("It doesn't touch the troop controls: the game already fills the right amount.",
                         "Ele não mexe nos controles de tropas: o jogo já preenche a quantidade certa."),
                    ),
                    tip("If your troops can't fill high-level nodes, lower the max level: the bot "
                        "wastes less time testing levels it would discard anyway.",
                        "Se suas tropas não enchem nós de nível alto, baixe o nível máximo: o bot "
                        "perde menos tempo testando níveis que vai acabar descartando."),
                    tip("If you also use Hunt (Terror/Beasts), set the resources you don't need to OFF "
                        "to leave march queues free for the rallies.",
                        "Se você também usa Caça (Terror/Bestas), deixe em OFF os recursos de que não "
                        "precisa para sobrar filas de marcha para os rallies."),
                    warn("The four gatherer heroes must be unlocked. Without the hero, the resource "
                         "is never sent.",
                         "Os quatro heróis coletores precisam estar desbloqueados. Sem o herói, "
                         "o recurso nunca é enviado."),
                ],
            },
            {
                "task": "Collect Conquest",
                "title": L("Conquest income", "Renda da Conquista"),
                "summary": L("Collects the idle income accumulated on the Conquest screen.",
                             "Coleta a renda ociosa acumulada na tela de Conquista."),
                "fields": [],
                "howto": [
                    p("Opens the Conquest button on the bottom bar and, if the green \"Claim\" button "
                      "is next to the chest, collects the idle income and returns to the city.",
                      "Abre o botão Conquest da barra inferior e, se o botão verde \"Claim\" "
                      "estiver ao lado do baú, coleta a renda ociosa e volta para a cidade."),
                    bullets(
                        ("Checks every 1 h.", "Verifica a cada 1 h."),
                        ("If the \"Claim\" button doesn't show, nothing has accumulated yet; the bot "
                         "just goes back.",
                         "Se o botão \"Claim\" não aparece, ainda não acumulou nada; o bot só volta."),
                    ),
                    NO_OPTIONS,
                ],
            },
        ],
        "panels": [PANEL_RESOURCE_STOCK],
    },
    {
        "id": "hunt",
        "title": L("Hunt", "Caça"),
        "tasks": [
            {
                "task": "Hunt Beasts",
                "title": L("Beasts (direct attack)", "Bestas (ataque direto)"),
                "summary": L("Attacks Beasts with the HNT formation while there is stamina.",
                             "Ataca Bestas com a formação HNT enquanto houver stamina."),
                "schedule": L("continuous, while there is stamina", "contínuo, enquanto houver stamina"),
                "fields": [
                    int_field("beast_level", ("Beast level", "Nível da Besta"), config.BEAST_LEVEL_MIN,
                              config.BEAST_LEVEL_MAX, config.BEAST_LEVEL_DEFAULT),
                    bool_field("beast_require_diana", ("Only attack with Diana in the formation",
                                                       "Só atacar com a Diana na formação"),
                               config.BEAST_REQUIRE_DIANA_DEFAULT,
                               help=("OFF: attacks even if Diana is away.",
                                     "OFF: ataca mesmo se a Diana estiver fora.")),
                ],
                "howto": [
                    p("Searches a Beast on the world map, attacks directly (no rally), loads the "
                      f"saved \"HNT\" formation and deploys. Each attack needs "
                      f"{config.BEAST_STAMINA_COST} stamina. Runs before Terror so it uses the "
                      "stamina first.",
                      "Busca uma Besta no mapa-múndi, ataca direto (sem rally), carrega a "
                      f"formação salva \"HNT\" e envia. Cada ataque precisa de "
                      f"{config.BEAST_STAMINA_COST} de stamina. Roda antes do Terror para "
                      "usar a stamina primeiro."),
                    h("In-game setup (once)", "Preparação no jogo (uma vez)"),
                    steps(
                        ("Open a march's formation screen (Deploy).",
                         "Abra a tela de formação de uma marcha (Deploy)."),
                        ("Build the team with Diana and the troop ratio you want (e.g. 50/20/30).",
                         "Monte o time com a Diana e a proporção de tropas que você quer "
                         "(ex.: 50/20/30)."),
                        ("Save it as a preset named exactly \"HNT\" (the bot looks for that text on "
                         "the presets tab).",
                         "Salve como predefinição com o nome exatamente \"HNT\" (o bot procura "
                         "esse texto na aba de predefinições)."),
                    ),
                    h("How to set it up", "Como ajustar"),
                    steps(
                        SWITCH_ON,
                        (f"In \"Beast level\" ({config.BEAST_LEVEL_MIN}–{config.BEAST_LEVEL_MAX}) pick "
                         "the level. The bot sets the game's selector and checks the number it reads "
                         "before searching.",
                         f"Em \"Nível da Besta\" ({config.BEAST_LEVEL_MIN}–{config.BEAST_LEVEL_MAX}) "
                         "escolha o nível. O bot ajusta o seletor do jogo e confere o número "
                         "lido antes de buscar."),
                        ("\"Only attack with Diana in the formation\": ON = if Diana is out on a march, "
                         "the bot doesn't attack and waits for her to return; OFF = attacks with "
                         "whatever the HNT preset manages to load.",
                         "\"Só atacar com a Diana na formação\": ON = se a Diana estiver fora "
                         "numa marcha, o bot não ataca e espera ela voltar; OFF = ataca com "
                         "o que a predefinição HNT conseguir carregar."),
                    ),
                    bullets(
                        ("Stamina is read from the game before each attack (never estimated).",
                         "A stamina é lida do jogo antes de cada ataque (nunca estimada)."),
                        ("Without enough stamina, it goes back to the city and waits to recharge "
                         f"(+1 every {config.STAMINA_MINUTES_PER_POINT} min).",
                         "Sem stamina suficiente, volta para a cidade e espera recarregar "
                         f"(+1 a cada {config.STAMINA_MINUTES_PER_POINT} min)."),
                    ),
                    warn("Without the saved \"HNT\" preset, the attack is cancelled.",
                         "Sem a predefinição \"HNT\" salva, o ataque é cancelado."),
                ],
            },
            {
                "task": "Hunt Terror",
                "title": L("Terror (rally)", "Terror (rally)"),
                "summary": L("Opens Terror rallies back-to-back while there is stamina.",
                             "Abre rallies de Terror em sequência enquanto houver stamina."),
                "schedule": L("continuous, while there is stamina", "contínuo, enquanto houver stamina"),
                "fields": [
                    int_field("terror_level", ("Terror level", "Nível do Terror"), config.TERROR_LEVEL_MIN,
                              config.TERROR_LEVEL_MAX, config.TERROR_LEVEL_DEFAULT),
                    choice_field("rally_mode", ("Rally mode", "Modo de rally"), [
                        ("hnt", ("HNT: 1 rally with the HNT formation", "HNT: 1 rally com a formação HNT")),
                        ("fill", ("Fill: every free queue", "Fill: todas as filas livres")),
                    ], config.TERROR_RALLY_MODE_DEFAULT),
                    bool_field("require_diana", ("Wait for Diana (HNT mode)", "Esperar a Diana (modo HNT)"),
                               config.TERROR_REQUIRE_DIANA_DEFAULT,
                               help=("OFF: sends without her (costs more stamina).",
                                     "OFF: envia sem ela (custa mais stamina).")),
                ],
                "howto": [
                    p("Searches a Terror on the world map, opens a rally with a 5 min arrival and "
                      "deploys. The bot stays on the map watching the march queues and relaunches as "
                      "soon as the rally returns, until stamina runs out.",
                      "Busca um Terror no mapa-múndi, abre um rally com chegada de 5 min e "
                      "envia. O bot fica no mapa acompanhando as filas de marcha e relança "
                      "assim que o rally volta, até a stamina acabar."),
                    h("How to set it up", "Como ajustar"),
                    steps(
                        SWITCH_ON,
                        (f"\"Terror level\" ({config.TERROR_LEVEL_MIN}–{config.TERROR_LEVEL_MAX}): "
                         "the level to hunt.",
                         f"\"Nível do Terror\" ({config.TERROR_LEVEL_MIN}–{config.TERROR_LEVEL_MAX}): "
                         "nível que será caçado."),
                        ("\"Rally mode\":\n"
                         "• HNT: one rally at a time with the \"HNT\" preset (Diana + ratio). "
                         f"Costs {config.TERROR_RALLY_COST_HNT} stamina.\n"
                         "• Fill: opens rallies on EVERY free queue without loading the preset; it uses "
                         "the heroes the game picks and taps \"Equalize\" to split the troops. "
                         f"Costs {config.TERROR_RALLY_COST_FILL} stamina each.",
                         "\"Modo de rally\":\n"
                         f"• HNT: um rally por vez com a predefinição \"HNT\" (Diana + proporção). "
                         f"Custa {config.TERROR_RALLY_COST_HNT} de stamina.\n"
                         "• Fill: abre rallies em TODAS as filas livres, sem carregar a predefinição; "
                         "usa os heróis que o jogo escolhe e toca \"Equalize\" para dividir as tropas. "
                         f"Custa {config.TERROR_RALLY_COST_FILL} de stamina cada."),
                        ("\"Wait for Diana\" (HNT mode only): ON = if Diana is away, it doesn't send and "
                         f"tries again in ~{config.TERROR_DIANA_WAIT_RETRY // 60} min; OFF = sends "
                         f"without her (costs {config.TERROR_RALLY_COST_FILL}).",
                         "\"Esperar a Diana\" (só no modo HNT): ON = se a Diana estiver fora, "
                         f"não envia e tenta de novo em ~{config.TERROR_DIANA_WAIT_RETRY // 60} min; "
                         f"OFF = envia sem ela (custa {config.TERROR_RALLY_COST_FILL})."),
                    ),
                    h("How it decides", "Como ele decide"),
                    bullets(
                        ("Stamina is read from the game before each rally. A lost rally doesn't spend "
                         "stamina, so it is never estimated.",
                         "A stamina é lida do jogo antes de cada rally. Um rally perdido não gasta "
                         "stamina, por isso ela nunca é estimada."),
                        (f"Out of stamina, it goes back to the city and waits until it has ~{config.TERROR_RECHARGE_TARGET}.",
                         f"Sem stamina, volta para a cidade e espera até juntar ~{config.TERROR_RECHARGE_TARGET}."),
                        ("It only reuses the queues it took itself: your gathers and other marches are "
                         "never touched.",
                         "Só reutiliza as filas que ele mesmo ocupou: suas coletas e outras marchas "
                         "não são tocadas."),
                        (f"If every queue is busy, it tries again in {config.TERROR_ALL_BUSY_RETRY // 60} min.",
                         f"Se todas as filas estão ocupadas, tenta de novo em "
                         f"{config.TERROR_ALL_BUSY_RETRY // 60} min."),
                        ("Options are re-read whenever a rally returns, so you can change the level "
                         "while the hunt is running.",
                         "As opções são relidas sempre que um rally volta, então dá para trocar o "
                         "nível com a caça em andamento."),
                    ),
                    tip("To use HNT mode, save in the game a formation preset named exactly \"HNT\" "
                        "with Diana in it (see the Beasts section).",
                        "Para usar o modo HNT, salve no jogo uma predefinição de formação com o "
                        "nome exatamente \"HNT\" contendo a Diana (veja a seção Bestas)."),
                ],
            },
            {
                "task": "Intel Missions",
                "title": L("Intel Missions", "Missões de Inteligência"),
                "summary": L("Dispatches the Intel panel missions (hunt, battle, rescue).",
                             "Despacha as missões do painel Intel (caça, batalha, resgate)."),
                "fields": [],
                "howto": [
                    p("Opens the Intel Mission panel (compass on the world map) and dispatches the "
                      "balloons by type and rarity.",
                      "Abre o painel Intel Mission (bússola no mapa-múndi) e despacha os "
                      "balões em ordem de tipo e raridade."),
                    bullets(
                        ("Type order: Monster hunts → Battles → Refugee rescues.",
                         "Ordem dos tipos: Caça a monstros → Batalhas → Resgate de refugiados."),
                        ("Within each type: gold/orange → purple → blue → green → white.",
                         "Dentro de cada tipo: dourado/laranja → roxo → azul → verde → branco."),
                        ("Monster hunts use a march queue; the bot taps \"Equalize\" and only deploys "
                         "if the game predicts a win (green message).",
                         "Caça a monstros usa fila de marcha; o bot toca \"Equalize\" e só envia se o "
                         "jogo prever vitória (mensagem verde)."),
                        ("Finished missions (green check) are skipped and \"Claim All\" collects the rewards.",
                         "Missões já concluídas (selo verde) são puladas e \"Claim All\" coleta as recompensas."),
                        ("Rebel Bounty (Gilded Baron) is done last and repeated until the first defeat.",
                         "Rebel Bounty (Gilded Baron) é feita por último e repetida até a primeira derrota."),
                        ("Runs every 6 h, before the Terror hunt, and never spends gems.",
                         "Roda a cada 6 h, antes da caça ao Terror, e nunca gasta gemas."),
                    ),
                    NO_OPTIONS,
                ],
            },
        ],
    },
    {
        "id": "alliance",
        "title": L("Alliance", "Aliança"),
        "tasks": [
            {
                "task": "Help alliance",
                "title": L("Help the alliance", "Ajudar a aliança"),
                "summary": L("Taps the help balloon (handshake) when it shows up.",
                             "Toca no balão de ajuda (aperto de mãos) quando ele aparece."),
                "fields": [],
                "howto": [
                    p("Checks every 1 min whether the help balloon is on the main screen and taps it, "
                      "helping every request at once. It doesn't open any window.",
                      "Verifica a cada 1 min se o balão de ajuda está na tela principal e toca "
                      "nele, ajudando todos os pedidos de uma vez. Não abre janelas."),
                    NO_OPTIONS,
                ],
            },
            {
                "task": "Alliance Chests",
                "title": L("Alliance chests", "Baús da aliança"),
                "summary": L("Opens the honor chest and collects Loot Chest and Alliance Gift.",
                             "Abre o baú de honra e coleta Loot Chest e Alliance Gift."),
                "fields": [],
                "howto": [
                    steps(
                        ("Opens Alliance → Chests.", "Abre Aliança → Chests."),
                        ("Opens the honor chest (the big one at the top) if it is ready. It never taps "
                         "\"Send Alliance Gift\".",
                         "Abre o baú de honra (o grande, no topo) se ele estiver pronto. Nunca toca "
                         "em \"Send Alliance Gift\"."),
                        ("Loot Chest tab: uses \"Claim All\" when available; stops if the daily limit "
                         "(500/500) was already reached.",
                         "Aba Loot Chest: usa \"Claim All\" quando disponível; para se o limite "
                         "diário (500/500) já foi atingido."),
                        ("Alliance Gift tab: uses \"Claim All\" or claims gift by gift.",
                         "Aba Alliance Gift: usa \"Claim All\" ou coleta presente por presente."),
                    ),
                    p("Runs every 30 min. There are no options besides the task's ON/OFF switch.",
                      "Roda a cada 30 min. Não há opções além da chave ON/OFF da tarefa."),
                ],
            },
            {
                "task": "Alliance Tech",
                "title": L("Alliance tech", "Tecnologia da aliança"),
                "summary": L("Spends the contribution points before they hit the cap.",
                             "Gasta os pontos de contribuição antes que acumulem no máximo."),
                "fields": [],
                "howto": [
                    p("Contribution points refill 1 every 10 min up to 25. Every 1 h the bot opens "
                      "Alliance → Tech → Battle tab → \"Covenant-Making\" and holds the RIGHT button "
                      "(which spends resources) until the attempts reach zero.",
                      "Os pontos de contribuição recarregam 1 a cada 10 min até 25. A cada 1 h o "
                      "bot abre Aliança → Tech → aba Battle → \"Covenant-Making\" e segura o botão "
                      "da DIREITA (que gasta recurso) até zerar as tentativas."),
                    warn("The LEFT button spends gems and is never used.",
                         "O botão da ESQUERDA gasta gemas e nunca é usado."),
                    warn("The task assumes your alliance's tech tree is already complete (only "
                         "Covenant-Making open). If it isn't, set this task to OFF.",
                         "A tarefa assume que a árvore de tecnologia da sua aliança já está completa "
                         "(só o Covenant-Making aberto). Se não estiver, deixe esta tarefa em OFF."),
                ],
            },
            {
                "task": "Buy VIP Points",
                "title": L("Buy VIP in the alliance shop", "Comprar VIP na loja da aliança"),
                "summary": L("Buys VIP XP cards with Alliance Tokens up to the chosen VIP.",
                             "Compra cartas de VIP XP com Alliance Tokens até o VIP escolhido."),
                "fields": [
                    int_field("vip_target_level", ("Buy until VIP", "Comprar até chegar no VIP"), 1,
                              config.VIP_LEVEL_MAX, config.VIP_TARGET_LEVEL_DEFAULT,
                              help=("Stops buying when the current VIP is equal or higher.",
                                    "Para de comprar quando o VIP atual for igual ou maior.")),
                ],
                "howto": [
                    p("Reads the current VIP level (VIP screen) and, while it is BELOW the target, buys "
                      "the maximum possible amount of the VIP XP cards (+10 and +100) on the Today and "
                      "Week tabs of the alliance shop, using Alliance Tokens.",
                      "Lê o nível VIP atual (tela VIP) e, enquanto ele estiver ABAIXO do alvo, "
                      "compra a quantidade máxima possível das cartas de VIP XP (+10 e +100) nas "
                      "abas Today e Week da loja da aliança, usando Alliance Tokens."),
                    h("How to set it up", "Como ajustar"),
                    steps(
                        SWITCH_ON,
                        ("In \"Buy until VIP\", enter the level you want. E.g. 6 = buys while the "
                         "account is VIP 5 or lower.",
                         "Em \"Comprar até chegar no VIP\", informe o nível desejado. Ex.: 6 = compra "
                         "enquanto a conta for VIP 5 ou menos."),
                    ),
                    bullets(
                        ("Runs every 6 h.", "Roda a cada 6 h."),
                        ("Buys even without a discount, always limited to the tokens you have.",
                         "Compra mesmo sem desconto, sempre limitado aos tokens que você tem."),
                        ("The VIP level read is saved on the account (shown at the top of the panel).",
                         "O nível VIP lido fica salvo na conta (aparece no topo do painel)."),
                    ),
                ],
            },
        ],
    },
    {
        "id": "troops",
        "title": L("Troops", "Tropas"),
        "tasks": [
            {
                "task": "Train troops",
                "title": L("Train troops", "Treinar tropas"),
                "summary": L("Trains infantry, cavalry and archers at the chosen tier.",
                             "Treina infantaria, cavalaria e arqueiros no tier escolhido."),
                "fields": [
                    int_field("train_tier", ("Tier", "Tier"), config.TRAIN_TIER_MIN,
                              config.TRAIN_TIER_MAX, config.TRAIN_TIER_DEFAULT,
                              help=("10 = Apex (the strongest).", "10 = Apex (o mais forte).")),
                ],
                "howto": [
                    p("Opens the barracks through the Power panel (fixed path, no map navigation) and, "
                      "on the training screen, goes through the three tabs: infantry, cavalry and archers.",
                      "Abre o quartel pelo painel de Poder (caminho fixo, sem depender do mapa) "
                      "e, na tela de treino, passa pelas três abas: infantaria, cavalaria e arqueiros."),
                    h("How to set it up", "Como ajustar"),
                    steps(
                        SWITCH_ON,
                        (f"In \"Tier\" ({config.TRAIN_TIER_MIN}–{config.TRAIN_TIER_MAX}), pick the tier "
                         "to train.",
                         f"Em \"Tier\" ({config.TRAIN_TIER_MIN}–{config.TRAIN_TIER_MAX}), escolha o "
                         "tier a treinar."),
                    ),
                    bullets(
                        ("If the chosen tier is still locked (\"Upgrade Now\" shows), the bot uses the "
                         "highest unlocked tier.",
                         "Se o tier escolhido ainda está bloqueado (aparece \"Upgrade Now\"), o bot "
                         "usa o maior tier desbloqueado."),
                        ("Types still training are skipped until the next pass.",
                         "Tipos que ainda estão treinando são pulados até a próxima passada."),
                        ("Runs every 3 h and, at the end, checks that all three trainings started.",
                         "Roda a cada 3 h e, no fim, confere se os três treinos começaram."),
                    ),
                    warn("The batch uses the MAXIMUM allowed amount, which spends a lot of resources.",
                         "O lote usa a quantidade MÁXIMA permitida, o que consome bastante recurso."),
                ],
            },
        ],
        "panels": [PANEL_TROOP_STOCK, PANEL_TROOP_PLAN],
    },
    {
        "id": "events",
        "title": L("Events", "Eventos"),
        "tasks": [],
        "panels": [PANEL_EVENTS],
    },
    {
        "id": "daily",
        "title": L("Dailies", "Diárias"),
        "tasks": [
            {
                "task": "Daily Missions",
                "title": L("Daily missions", "Missões diárias"),
                "summary": L("Claims finished missions and the activity chests.",
                             "Coleta missões concluídas e os baús de atividade."),
                "fields": [],
                "howto": [
                    p("Every 1 h it opens the missions scroll (Daily tab), uses \"Claim All\" and closes "
                      "the milestone chests that open by themselves.",
                      "A cada 1 h abre o pergaminho de missões (aba Daily), usa \"Claim All\" e fecha "
                      "os baús de marco que abrem sozinhos."),
                    p("For pending missions that have a matching bot task (help alliance, tech, arena, "
                      "train troops), it runs that task and claims again. Tasks switched OFF for this "
                      "account are NOT run from here.",
                      "Para missões pendentes que têm tarefa equivalente no bot (ajudar aliança, "
                      "tecnologia, arena, treinar tropas), ele executa essa tarefa e coleta de novo. "
                      "Tarefas desligadas nesta conta NÃO são executadas por aqui."),
                    p("The only \"Go\" button used is the free hero recruitment one.",
                      "O único botão \"Go\" usado é o de recrutamento grátis de herói."),
                ],
            },
            {
                "task": "Collect VIP daily",
                "title": L("Daily VIP rewards", "Recompensas VIP diárias"),
                "summary": L("Collects the day's VIP points and the free daily bundle.",
                             "Coleta os pontos VIP do dia e o pacote grátis diário."),
                "fields": [],
                "howto": [
                    p("Runs once per bot run: opens the VIP screen, collects the daily points chest "
                      "and, if VIP is active, the \"VIP Daily Free Bundle\".",
                      "Roda uma vez por execução do bot: abre a tela VIP, coleta o baú de pontos "
                      "diários e, se o VIP estiver ativo, o \"VIP Daily Free Bundle\"."),
                ],
            },
            {
                "task": "Governor Order",
                "title": L("Governor Orders", "Ordens do Governador"),
                "summary": L("Issues Productivity, Rush Job and Festivities in sequence.",
                             "Emite Productivity, Rush Job e Festivities em sequência."),
                "fields": [],
                "howto": [
                    p("Every 12 h it opens the governor orders (scales icon) and issues, in this order: "
                      "Productivity (50,000 stars), Rush Job (150,000) and Festivities (50,000).",
                      "A cada 12 h abre as ordens do governador (ícone da balança) e emite, nesta "
                      "ordem: Productivity (50.000 estrelas), Rush Job (150.000) e Festivities (50.000)."),
                    bullets(
                        ("Needs at least 250,000 stars; with fewer, no order is issued.",
                         "Precisa de pelo menos 250.000 estrelas; com menos, nenhuma ordem é emitida."),
                        ("Active orders or orders on cooldown are skipped.",
                         "Ordens ativas ou em recarga são puladas."),
                    ),
                ],
            },
            {
                "task": "Rebel Conquest",
                "title": L("Rebel Assault", "Ataque Rebelde"),
                "summary": L("Resolves the Rebel Assault with Quick Challenge.",
                             "Resolve o Rebel Assault com o Quick Challenge."),
                "fields": [],
                "howto": [
                    p("Every 10 min it looks for the Rebel Assault icon (top-left corner). If it is "
                      "there, it uses \"Quick Challenge\" and claims the rewards.",
                      "A cada 10 min procura o ícone do Rebel Assault (canto superior esquerdo). "
                      "Se existir, usa \"Quick Challenge\" e coleta as recompensas."),
                    warn("Quick Challenge only shows when your power guarantees the win. Without it, "
                         "the bot closes the window and does NOT fight manually.",
                         "O Quick Challenge só aparece quando seu poder garante a vitória. Sem ele, "
                         "o bot fecha a janela e NÃO faz a batalha manual."),
                ],
            },
            {
                "task": "Arena of Glory",
                "title": L("Arena (PVP)", "Arena (PVP)"),
                "summary": L("Does the daily Arena challenges against weaker opponents.",
                             "Faz os desafios diários da Arena contra oponentes mais fracos."),
                "fields": [],
                "howto": [
                    p(f"Every 1 h it opens the Arena of Glory and does up to "
                      f"{config.ARENA_MAX_CHALLENGES} challenges.",
                      f"A cada 1 h abre a Arena of Glory e faz até {config.ARENA_MAX_CHALLENGES} "
                      "desafios."),
                    bullets(
                        ("Reads your power and each opponent's and picks the weakest one with up to "
                         f"{int(config.ARENA_MAX_OPPONENT_RATIO * 100)}% of your power.",
                         "Lê o seu poder e o de cada oponente e escolhe o mais fraco com até "
                         f"{int(config.ARENA_MAX_OPPONENT_RATIO * 100)}% do seu poder."),
                        ("Never challenges anyone stronger than you.",
                         "Nunca desafia alguém mais forte que você."),
                    ),
                ],
            },
        ],
    },
]


def iter_tasks():
    for section in SECTIONS:
        yield from section["tasks"]


FIELDS = {field["key"]: field for task in iter_tasks() for field in task["fields"]}

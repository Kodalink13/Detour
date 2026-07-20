import os
import random
import time
import hashlib
import curses
import locale

locale.setlocale(locale.LC_ALL, '')

# ============================================
# HASH DETERMINÍSTICO
# ============================================
def det_hash(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16)

# ============================================
# MUNDO CONTÍNUO — sem chunks. Cada tile é gerado
# sob demanda a partir da coordenada absoluta (wx,wy),
# então não existe "transição" de setor: é tudo o
# mesmo espaço, a câmera só rola ao redor do XEON.
# ============================================
WORLD_SEED = 1337
BASE_POS = (0, 0)
PIREPLI_POS = (6, -3)   # mutável — ele se move durante combate
JEANO_POS = (-8, 5)

player_nation = None   # None = independente; senão nome da nação aliada
has_vent_rapide = False   # artefato exclusivo da França: velocidade nível 4
PIREPLI_PRICE_MULT_FRANCE = 1.5   # aliança com a França azeda a relação comercial c/ PIREPLI

def recompute_speed():
    global turn_cost_per_move
    level = 1
    if has_leggero:
        level = max(level, 2)
    if has_vent_rapide:
        level = max(level, 4)
    turn_cost_per_move = 1.0 / level

VIEW_W, VIEW_H = 30, 12   # janela da câmera (em tiles) — reduzida pra abrir margem vertical
DAY_LENGTH = 3000

destroyed_rocks = set()   # (wx, wy)
destroyed_trees = set()   # (wx, wy)

def tile_type(wx, wy):
    if (wx, wy) == BASE_POS or (wx, wy) == PIREPLI_POS or (wx, wy) == JEANO_POS:
        return '.'
    if (wx, wy) in destroyed_rocks or (wx, wy) in destroyed_trees:
        return '.'
    h = det_hash(f"{wx}_{wy}_{WORLD_SEED}_terrain")
    r = (h % 1000) / 1000.0
    if r < 0.05:
        return '#'
    elif r < 0.09:
        return 'T'
    return '.'

# ============================================
# STATUS DO XEON
# ============================================
player_wx, player_wy = 0, 0
turns = 0
energy = 100.0
hp = 100
max_hp = 100

tether_active = True
max_tether_dist = 150
CABLE_MAX_DIST = 60
cables = set()             # (wx, wy) — posições com cabo laçado
mining_mode = False
examine_msg = ""
heading_deg = 0
wireless_efficiency = 1.0

inventory = {"minerio": 0, "madeira": 0, "diamante": 0, "pá": 0, "cicero_extractor": 0}
DIAMANTE_VALOR_MINERIO = 5

has_leggero = False
turn_cost_per_move = 1.0
turn_accum = 0.0

CICERO_TOTAL = 10
CICERO_DURATION = 12
extractors = {}            # (wx, wy) -> {"ticks","given","ready"}

DIG_ENERGY_COST = 4
DIAMOND_CHANCE = 0.35

artifact_infinite_energy = False
artifact_no_mining_damage = False

# combate mínimo — arma de teste no slot 1, só o suficiente pra validar
# o fluxo de mira. Quando o sistema de armas de verdade existir, isso
# vira "o que tá equipado no slot 1" em vez de fixo.
WEAPON_RANGE = 6
WEAPON_DAMAGE = (8, 14)
aim_cursor = None

pirepli_hp = 30
pirepli_hostile = False
pirepli_dead = False
pirepli_dmg_mult = 1.0   # sobe 30% a cada revide — ele fica mais bravo/perigoso
has_voltaire_lrhd = False   # arma dada pelo JEANO junto com o Vent Rapide

jeano_hp = 30
jeano_hostile = False
jeano_dead = False
jeano_dmg_mult = 1.0

BASE_MAX_HP = 100
base_hp = 100

has_palatini = False
equipped_weapon = "voltaire"   # "voltaire" ou "palatini" — mesmo dano, é escolha de flavor/inventário
jeano_betrayed = False   # JEANO morto, mas os VEX só spawnam quando você fala com o PIREPLI
pirepli_quest_active = False
vex_units = []   # cada um: {"x", "y", "hp"}
VEX_MAX_HP = 10

PALATINI_ART = [
    "  _________",
    " /.        ^",
    " \\________V",
    " |_|.  |/",
]

VEX_GLYPH = " v "   # ASCII puro, cor (vermelho hostil) já carrega a identidade

VOLTAIRE_LRHD_ART = [
    "  ,________",
    " /  VOLT   /////",
    " \\________/////",
    " /_/.   \\)",
]

VISION_RADIUS = 5
revealed_tiles = set()     # (wx, wy)

def reveal_around_player():
    for dy in range(-VISION_RADIUS, VISION_RADIUS + 1):
        for dx in range(-VISION_RADIUS, VISION_RADIUS + 1):
            revealed_tiles.add((player_wx + dx, player_wy + dy))

HEADING_NAMES = {0: "N", 90: "L", 180: "S", 270: "O"}

# glifo = letra simples colorida, estilo Cogmind (ASCII puro, sem risco
# de renderização — a identidade vem da COR, não do caractere)
NATION_GLYPH = {"XEON": " @ ", "JEANO": " j ", "GODELI": " g ", "PIREPLI": " p "}

# ============================================
# DADOS DE NAÇÃO / MARCA / ARMA — referência formal,
# ainda não plugada em loja/combate, mas pronta pra isso.
# ============================================
NATIONS = {
    "XEON":    {"pais": "China",     "robo": "XEON",    "marcas": [],
                "papel": "jogável"},
    "PIREPLI": {"pais": "Itália",    "robo": "PIREPLI", "marcas": ["PALADIN INDUSTRIES (= Palatini, nome original)"],
                "foco": "engines e armas leves, velocidade",
                "papel": "wanderer neutro; alíança só liberada após quests (dá o artefato de energia infinita sem tether)"},
    "JEANO":   {"pais": "França",    "robo": "JEANO",   "marcas": ["VOLTAIRE"],
                "foco": "elétrico, cobre longo alcance e corpo a corpo, mobilidade",
                "papel": "diplomata; aliança disponível desde já (dá o Vent Rapide, velocidade nível 4)"},
    "SCHEAFER":{"pais": "EUA",       "robo": "SCHEAFER","marcas": ["SHEAFFER"],
                "foco": "precisão / longo alcance"},
    "GODELI":  {"pais": "Alemanha",  "robo": "GODELI",  "marcas": ["VOLTAIRE+SHEAFFER (mix)", "BELLBERG"],
                "foco": "generalista + armas pesadas de alta eficiência"},
}

WEAPONS = {
    "SHEAFFER_LONG_SIERRA":  {"marca": "SHEAFFER", "nacao": "SCHEAFER", "tipo": "rifle longo alcance"},
    "VOLTAIRE_LRHD_04":      {"marca": "VOLTAIRE",  "nacao": "JEANO",    "tipo": "rifle elétrico / coil"},
    "PALATINI_SLIP_CANNON":  {"marca": "PALATINI",  "nacao": "PIREPLI",  "tipo": "canhão pesado"},
    "VOLTAIRE_SPEAR":        {"marca": "VOLTAIRE",  "nacao": "JEANO",    "tipo": "melee"},
}

dist = 0
stdscr = None

# ============================================
# CORES
# ============================================
COLORS_ENABLED = False
C_HP, C_EN, C_XEON, C_JEANO, C_GODELI, C_PIREPLI, C_ROCK, C_TREE, C_CABLE, C_BASE, C_DIAMOND, C_DIM = range(1, 13)

def cp(n):
    return curses.color_pair(n) if COLORS_ENABLED else curses.A_NORMAL

def setup_colors():
    global COLORS_ENABLED
    if not curses.has_colors():
        COLORS_ENABLED = False
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(C_HP, curses.COLOR_RED, bg)
    curses.init_pair(C_EN, curses.COLOR_CYAN, bg)
    curses.init_pair(C_XEON, curses.COLOR_CYAN, bg)   # independente = azul claro/ciano
    curses.init_pair(C_JEANO, curses.COLOR_BLUE, bg)
    curses.init_pair(C_GODELI, curses.COLOR_YELLOW, bg)
    curses.init_pair(C_PIREPLI, curses.COLOR_GREEN, bg)
    curses.init_pair(C_ROCK, curses.COLOR_WHITE, bg)
    curses.init_pair(C_TREE, curses.COLOR_GREEN, bg)
    curses.init_pair(C_CABLE, curses.COLOR_CYAN, bg)
    curses.init_pair(C_BASE, curses.COLOR_YELLOW, bg)
    curses.init_pair(C_DIAMOND, curses.COLOR_MAGENTA, bg)
    curses.init_pair(C_DIM, curses.COLOR_WHITE, bg)
    COLORS_ENABLED = True

def safe_addstr(y, x, text, attr=curses.A_NORMAL):
    maxy, maxx = stdscr.getmaxyx()
    if y < 0 or y >= maxy or x >= maxx:
        return
    if x < 0:
        text = text[-x:]
        x = 0
    if x + len(text) > maxx:
        text = text[:maxx - x]
    if text:
        try:
            stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

def line_tiles(x0, y0, x1, y1):
    """Bresenham simples — devolve os tiles entre dois pontos, do começo ao fim."""
    tiles = []
    dx = abs(x1 - x0); dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        tiles.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy; x += sx
        if e2 <= dx:
            err += dx; y += sy
    return tiles

def xeon_color():
    if player_nation == "França (JEANO)":
        return cp(C_JEANO)
    elif player_nation == "Itália (PIREPLI)":
        return cp(C_PIREPLI)
    return cp(C_XEON)

def is_connected(wx, wy):
    return (wx, wy) == BASE_POS or (wx, wy) in cables

def is_on_base():
    return (player_wx, player_wy) == BASE_POS

def is_adjacent_to_pirepli():
    if pirepli_dead:
        return False
    return abs(player_wx - PIREPLI_POS[0]) <= 1 and abs(player_wy - PIREPLI_POS[1]) <= 1

def is_adjacent_to_jeano():
    if jeano_dead:
        return False
    return abs(player_wx - JEANO_POS[0]) <= 1 and abs(player_wy - JEANO_POS[1]) <= 1

# ============================================
# RENDER — janela de câmera rola em torno do XEON,
# nunca "troca de tela"; sem clear(), curses só
# atualiza o que mudou.
# ============================================
def draw_screen():
    display_energy = max(0, int(energy))
    en_bars = display_energy // 5
    hp_bars = max(0, hp) // 5
    current_day = (turns // DAY_LENGTH) + 1
    rumo = HEADING_NAMES.get(heading_deg, "?")

    row = 0
    safe_addstr(row, 0, " XEON // CONTROL DECK ".center(100, '═')); row += 1
    safe_addstr(row, 0, f" POS [{player_wx},{player_wy}]   DIA {current_day}   TURNO {turns}   DIST {dist}km".ljust(100)); row += 1
    safe_addstr(row, 0, f" HP  [{'#' * hp_bars}{'-' * (20 - hp_bars)}] {hp}%  ".ljust(100), cp(C_HP)); row += 1
    safe_addstr(row, 0, f" EN  [{'#' * en_bars}{'-' * (20 - en_bars)}] {display_energy}%  ".ljust(100), cp(C_EN)); row += 1
    safe_addstr(row, 0, f" RUMO {heading_deg}° ({rumo})   MINERIOS {inventory['minerio']}   MADEIRA {inventory['madeira']}   DIAMANTES {inventory['diamante']}".ljust(100)); row += 1
    safe_addstr(row, 0, f" TETHER: {'[LIGADO]' if tether_active else '[DESLIGADO]'}   AÇÃO: {'[† PREPARADA]' if mining_mode else '[MOVIMENTO]'}".ljust(100)); row += 1
    status_extra = ""
    if pirepli_hostile and not pirepli_dead:
        status_extra = f" | PIREPLI: HOSTIL ({max(pirepli_hp,0)}/30 HP)"
    elif pirepli_dead:
        status_extra = " | PIREPLI: destruído"
    elif jeano_hostile and not jeano_dead:
        status_extra = f" | JEANO: HOSTIL ({max(jeano_hp,0)}/30 HP)"
    elif jeano_dead:
        status_extra = " | JEANO: destruído"
    safe_addstr(row, 0, f" NAÇÃO: {player_nation if player_nation else 'Independente'}{status_extra}".ljust(100), cp(C_HP) if status_extra else curses.A_NORMAL)
    row += 1
    itens = []
    if has_leggero: itens.append("Leggero Engine")
    if inventory["pá"] > 0: itens.append(f"Pá x{inventory['pá']}")
    if artifact_infinite_energy: itens.append("[ARTEFATO] Núcleo Perpétuo")
    if artifact_no_mining_damage: itens.append("[ARTEFATO] Blindagem Inabalável")
    if has_vent_rapide: itens.append("[ARTEFATO] Vent Rapide (França)")
    if has_voltaire_lrhd or has_palatini:
        nome = "Palatini Slip Cannon" if equipped_weapon == "palatini" else "Voltaire LRHD 04"
        itens.append(f"Equipada: {nome}")
    if pirepli_quest_active:
        vivos = sum(1 for v in vex_units if v["hp"] > 0)
        itens.append(f"[QUEST] VEX restantes: {vivos}")
    safe_addstr(row, 0, f" ITENS: {', '.join(itens) if itens else '-'}".ljust(100)); row += 1
    safe_addstr(row, 0, "═" * 100); row += 1
    map_top = row + 1

    panel_lines = [
        "CONTROLES", "─" * 22,
        "[↑↓←→] mover",
        "[C] cabo  [X] picareta",
        "[E] inspecionar",
        "[T] falar c/ NPC",
        "[V] Cicero+  [R] Cicero-",
        "[B] base  [P] cavar",
        "[I] inventário",
        "[1] atirar  [N] arma",
        "[Q] sair",
        "[Y]/[U] debug artefatos",
    ]
    panel_x = VIEW_W * 3 + 3

    cam_x = player_wx - VIEW_W // 2
    cam_y = player_wy - VIEW_H // 2

    trail_tiles = set()
    if aim_cursor:
        full_line = line_tiles(player_wx, player_wy, aim_cursor[0], aim_cursor[1])
        trail_tiles = set(full_line[1:-1])   # sem contar a ponta (XEON) nem o cursor
    npc_visible_now = (PIREPLI_POS[0] - cam_x, PIREPLI_POS[1] - cam_y)

    for sy in range(VIEW_H):
        wy = cam_y + sy
        col = 0
        for sx in range(VIEW_W):
            wx = cam_x + sx
            cell_y = map_top + sy
            cell_x = col
            visible = (wx, wy) in revealed_tiles

            if (wx, wy) == (player_wx, player_wy):
                glyph = "(@)" if mining_mode else NATION_GLYPH['XEON']
                safe_addstr(cell_y, cell_x, glyph, xeon_color() | curses.A_BOLD)
            elif aim_cursor and (wx, wy) == aim_cursor:
                safe_addstr(cell_y, cell_x, "[+]", curses.A_REVERSE | curses.A_BOLD)
            elif (wx, wy) in trail_tiles:
                safe_addstr(cell_y, cell_x, " @ ", cp(C_HP) | curses.A_BOLD)
            elif not visible:
                safe_addstr(cell_y, cell_x, "   ")
            elif (wx, wy) == BASE_POS:
                if player_nation == "França (JEANO)":
                    safe_addstr(cell_y, cell_x, "[F]", cp(C_JEANO) | curses.A_BOLD)
                elif player_nation == "Itália (PIREPLI)":
                    safe_addstr(cell_y, cell_x, "[I]", cp(C_PIREPLI) | curses.A_BOLD)
                else:
                    safe_addstr(cell_y, cell_x, "[B]", cp(C_BASE) | curses.A_BOLD)
            elif (wx, wy) == PIREPLI_POS and not pirepli_dead:
                safe_addstr(cell_y, cell_x, NATION_GLYPH['PIREPLI'], cp(C_PIREPLI) | curses.A_BOLD)
            elif (wx, wy) == JEANO_POS and not jeano_dead:
                safe_addstr(cell_y, cell_x, NATION_GLYPH['JEANO'], cp(C_JEANO) | curses.A_BOLD)
            elif any(v["hp"] > 0 and (v["x"], v["y"]) == (wx, wy) for v in vex_units):
                safe_addstr(cell_y, cell_x, VEX_GLYPH, cp(C_HP) | curses.A_BOLD)
            elif (wx, wy) in extractors:
                ext = extractors[(wx, wy)]
                safe_addstr(cell_y, cell_x, " Ø*" if ext["ready"] > 0 else " Ø ", cp(C_DIAMOND))
            elif (wx, wy) in cables:
                safe_addstr(cell_y, cell_x, " ~ ", cp(C_CABLE))
            else:
                t = tile_type(wx, wy)
                if t == '#':
                    safe_addstr(cell_y, cell_x, " # ", cp(C_ROCK))
                elif t == 'T':
                    safe_addstr(cell_y, cell_x, " T ", cp(C_TREE))
                else:
                    safe_addstr(cell_y, cell_x, " . ", cp(C_DIM))
            col += 3

        panel = panel_lines[sy] if sy < len(panel_lines) else ""
        safe_addstr(map_top + sy, panel_x, panel.ljust(24))

    safe_addstr(map_top + VIEW_H, 0, "═" * 100)
    msg_row = map_top + VIEW_H + 1
    if examine_msg:
        safe_addstr(msg_row, 0, ("» " + examine_msg.replace(chr(10), '  ')).ljust(100), curses.A_DIM)
    else:
        safe_addstr(msg_row, 0, " " * 100)

    stdscr.refresh()

# ============================================
# MENUS — suspendem o curses e voltam depois
# ============================================
def with_terminal(func):
    curses.endwin()
    try:
        func()
    finally:
        stdscr.touchwin()
        stdscr.refresh()

def _talk_to_pirepli_text():
    global has_leggero, has_palatini, pirepli_quest_active
    os.system('clear')

    if jeano_betrayed and not has_palatini:
        print("=== PIREPLI [Andarilho — Itália, neutro] ===\n")
        print("PIREPLI: 'Ouvi dizer que o JEANO caiu, amico.'")
        print("PIREPLI: 'Bem-vindo à causa — mas confiança se prova, não se declara.'")
        print("PIREPLI: 'Elimine os 2 VEX que restaram na posição dele. Prove seu valor.'")
        print("PIREPLI: 'Enquanto isso, aceite esta Palatini Slip Cannon. Vai precisar dela.'\n")
        has_palatini = True
        pirepli_quest_active = True
        jx, jy = JEANO_POS
        vex_units.append({"x": jx, "y": jy, "hp": VEX_MAX_HP})
        spot2 = (jx + 1, jy) if tile_type(jx + 1, jy) == '.' else (jx, jy + 1)
        vex_units.append({"x": spot2[0], "y": spot2[1], "hp": VEX_MAX_HP})
        print("[QUEST] 2 VEX apareceram na posição onde o JEANO estava.")
        print("Use [N] pra escolher qual arma equipar.")
        input("\n[ENTER pra continuar]")
        return

    price_mult = PIREPLI_PRICE_MULT_FRANCE if player_nation == "França (JEANO)" else 1.0
    leggero_price = int(-(-8 * price_mult // 1))    # arredonda pra cima
    cicero_price = int(-(-12 * price_mult // 1))
    print("=== PIREPLI [Andarilho — Itália, neutro] ===\n")
    print("PIREPLI: 'Belissimo Standard! I vow your attention.'")
    print("PIREPLI: 'I am no enemy - No no! i reckon peace!'")
    print("PIREPLI: 'Im only to sell. Parla is cheap, let me show you my itens, carissimo Standard:'\n")
    if price_mult > 1.0:
        print("PIREPLI: '...ma seus amici franceses non me fazem bem pros negócios. Preço sobe, mi dispiace.'\n")
    print(f" Seus minérios: {inventory['minerio']}\n")
    print(f" 1) Leggero Engine (PALADIN INDUSTRIES) -- {leggero_price} minérios")
    print("    -25% na taxa de consumo de energia em tether. Velocidade nível 2")
    print(f" 2) Cicero Extractor (PALADIN INDUSTRIES) -- {cicero_price} minérios")
    print(f"    planta numa pedra, rende {CICERO_TOTAL} minérios ao longo de {CICERO_DURATION} turnos")
    print(" 3) 'so passando' — sair da conversa")
    choice = input("\nEscolha: ").strip()
    if choice == '1':
        if has_leggero:
            print("\nPIREPLI: 'Já vendi esse pra você, carissimo. Um por robô, eh.'")
        elif inventory["minerio"] >= leggero_price:
            inventory["minerio"] -= leggero_price
            has_leggero = True
            recompute_speed()
            print("\nPIREPLI: 'Bellissimo! Leggero instalado.'")
        else:
            print(f"\nPIREPLI: 'Mh, faltam minérios, amico. Volte com {leggero_price}.'")
    elif choice == '2':
        if inventory["minerio"] >= cicero_price:
            inventory["minerio"] -= cicero_price
            inventory["cicero_extractor"] += 1
            print("\nPIREPLI: 'Cicero na bagagem!'")
        else:
            print("\nPIREPLI: 'Sem minério suficiente, carissimo.'")
    else:
        print("\nPIREPLI: 'Va bene. Talvez a gente se cruze de novo.'")
    input("\n[ENTER pra continuar]")

def _base_menu_text():
    os.system('clear')
    print("=== BASE — Fabricação ===\n")
    print(f" Minérios: {inventory['minerio']} | Gravetos: {inventory['madeira']} | Pás: {inventory['pá']}\n")
    print(" 1) Pá  --  10 minérios + 5 gravetos")
    print(" 2) Sair")
    choice = input("\nEscolha: ").strip()
    if choice == '1':
        if inventory["minerio"] >= 10 and inventory["madeira"] >= 5:
            inventory["minerio"] -= 10
            inventory["madeira"] -= 5
            inventory["pá"] += 1
            print("\nBASE: 'Pá fabricada com sucesso.'")
        else:
            falta = []
            if inventory["minerio"] < 10:
                falta.append(f"{10 - inventory['minerio']} minério(s)")
            if inventory["madeira"] < 5:
                falta.append(f"{5 - inventory['madeira']} graveto(s)")
            print(f"\nBASE: 'Recursos insuficientes. Faltam: {', '.join(falta)}.'")
    else:
        print("\nBASE: 'Até a próxima.'")
    input("\n[ENTER pra continuar]")

def _show_inventory_text():
    os.system('clear')
    print("=== INVENTÁRIO ===\n")
    print(f" Minérios:  {inventory['minerio']}")
    print(f" Madeira:   {inventory['madeira']}")
    print(f" Diamantes: {inventory['diamante']}  (cada um vale {DIAMANTE_VALOR_MINERIO} minérios)")
    print(f" Pás:       {inventory['pá']}")
    print(f" Cicero Extractor (não plantado): {inventory['cicero_extractor']}")
    print(f" Leggero Engine instalado: {'sim' if has_leggero else 'não'}")
    if has_vent_rapide or has_voltaire_lrhd:
        print("\n--- ITENS DA FRANÇA (JEANO) ---")
        if has_vent_rapide:
            print(" [ARTEFATO] Vent Rapide — velocidade nível 4")
        if has_voltaire_lrhd:
            marca = " (equipada)" if equipped_weapon == "voltaire" else ""
            print(f" Voltaire LRHD 04 (rifle elétrico, slot 1){marca}")
            for line in VOLTAIRE_LRHD_ART:
                print("   " + line)
    if has_palatini:
        print("\n--- ITENS DA PALADIN/PALATINI (PIREPLI) ---")
        marca = " (equipada)" if equipped_weapon == "palatini" else ""
        print(f" Palatini Slip Cannon (canhão pesado, slot 1){marca}")
        for line in PALATINI_ART:
            print("   " + line)
        print(" Use [N] pra trocar qual arma tá equipada.")
    input("\n[ENTER pra continuar]")

def _talk_to_jeano_text():
    global player_nation, has_vent_rapide, has_voltaire_lrhd
    os.system('clear')
    print("=== JEANO [França] ===\n")
    if player_nation == "França (JEANO)":
        print("JEANO: 'Toujours fidèle, mon ami? Bem, nossa aliança segue firme.'")
        input("\n[ENTER pra continuar]")
        return

    print("JEANO: 'Tiens, un robot solitaire. Você constrói sua metrópole sozinho, hein?'")
    print("JEANO: 'A França oferece proteção, comércio, mobilidade e armamento a quem se juntar a nós.'\n")
    print(f" Nação atual: {player_nation if player_nation else 'Independente'}\n")
    print(" 1) Aceitar aliança com a França (JEANO)")
    print(" 2) Recusar, permanecer independente")
    print(" 3) Sair da conversa")

    choice = input("\nEscolha: ").strip()
    if choice == '1':
        player_nation = "França (JEANO)"
        has_vent_rapide = True
        has_voltaire_lrhd = True
        recompute_speed()
        print("\nJEANO: 'Bienvenue! Sua bandeira agora tremula ao lado da nossa.'")
        print("JEANO: 'Receba o artefato Vent Rapide — você anda com o vento agora.'")
        print("       (Velocidade nível 4: 4 passos custam só 1 turno)")
        print("JEANO: 'E leve também uma Voltaire LRHD 04. Use com sabedoria.'")
    elif choice == '2':
        print("\nJEANO: 'Como preferir. A oferta continua de pé, caso mude de ideia.'")
    else:
        print("\nJEANO: 'Au revoir, então.'")
    input("\n[ENTER pra continuar]")

def move_pirepli():
    """Persegue o jogador — não foge mais, avança."""
    global PIREPLI_POS
    px, py = PIREPLI_POS
    best, best_dist = None, None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = px + dx, py + dy
            if (nx, ny) in (BASE_POS, JEANO_POS):
                continue
            if tile_type(nx, ny) != '.':
                continue
            d = abs(nx - player_wx) + abs(ny - player_wy)
            if best_dist is None or d < best_dist:
                best_dist, best = d, (nx, ny)
    if best:
        PIREPLI_POS = best

def move_jeano():
    global JEANO_POS
    px, py = JEANO_POS
    best, best_dist = None, None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = px + dx, py + dy
            if (nx, ny) in (BASE_POS, PIREPLI_POS):
                continue
            if tile_type(nx, ny) != '.':
                continue
            d = abs(nx - player_wx) + abs(ny - player_wy)
            if best_dist is None or d < best_dist:
                best_dist, best = d, (nx, ny)
    if best:
        JEANO_POS = best

def pirepli_ai_turn():
    """Roda em TODO turno (atirando, andando ou minerando) enquanto ele
    tá hostil — ele persegue e ataca se chegar no alcance, não só quando
    você atira nele."""
    global hp, pirepli_dmg_mult, examine_msg
    if not pirepli_hostile or pirepli_dead or pirepli_hp <= 0:
        return
    move_pirepli()
    if abs(player_wx - PIREPLI_POS[0]) <= WEAPON_RANGE and abs(player_wy - PIREPLI_POS[1]) <= WEAPON_RANGE:
        rdmg = round(random.randint(12, 22) * pirepli_dmg_mult)
        hp -= rdmg
        pirepli_dmg_mult *= 1.3
        msg = f"PIREPLI ataca! Você perde {rdmg} HP ({max(hp,0)}/{max_hp})."
        examine_msg = (examine_msg + "  »  " + msg) if examine_msg else msg

def jeano_ai_turn():
    global hp, jeano_dmg_mult, examine_msg
    if not jeano_hostile or jeano_dead or jeano_hp <= 0:
        return
    move_jeano()
    if abs(player_wx - JEANO_POS[0]) <= WEAPON_RANGE and abs(player_wy - JEANO_POS[1]) <= WEAPON_RANGE:
        rdmg = round(random.randint(10, 18) * jeano_dmg_mult)
        hp -= rdmg
        jeano_dmg_mult *= 1.3
        msg = f"JEANO ataca! Você perde {rdmg} HP ({max(hp,0)}/{max_hp})."
        examine_msg = (examine_msg + "  »  " + msg) if examine_msg else msg

def fire_at(tx, ty):
    global pirepli_hp, pirepli_hostile, pirepli_dead, examine_msg
    global jeano_hp, jeano_hostile, jeano_dead, player_nation, artifact_infinite_energy
    global has_palatini, pirepli_quest_active, hp, jeano_betrayed

    weapon_name = "Palatini Slip Cannon" if equipped_weapon == "palatini" else "Voltaire LRHD 04"

    if (tx, ty) == PIREPLI_POS and not pirepli_dead:
        if player_nation != "França (JEANO)":
            examine_msg = "Você não tem motivo pra atacar o PIREPLI (ainda)."
            return
        dmg = random.randint(*WEAPON_DAMAGE)
        pirepli_hostile = True
        pirepli_hp -= dmg
        if pirepli_hp <= 0:
            pirepli_dead = True
            examine_msg = f"Sua {weapon_name} acerta o PIREPLI ({dmg} de dano). PIREPLI: 'Non... impossibile...' Ele desaba, destruído."
        else:
            examine_msg = f"Sua {weapon_name} acerta o PIREPLI ({dmg} de dano, {max(pirepli_hp,0)}/30 HP)."
        advance_turn(1.0)
        return

    if (tx, ty) == JEANO_POS and not jeano_dead:
        if player_nation != "França (JEANO)" or not has_voltaire_lrhd:
            examine_msg = "Você não tem motivo pra trair o JEANO (ainda)."
            return
        dmg = random.randint(*WEAPON_DAMAGE)
        jeano_hostile = True
        jeano_hp -= dmg
        if jeano_hp <= 0:
            jeano_dead = True
            player_nation = None
            jeano_betrayed = True
            examine_msg = (f"Sua Voltaire se vira contra ele ({dmg} de dano). "
                            "JEANO: 'Trahison...' Ele cai, destruído. Procure o PIREPLI.")
        else:
            examine_msg = f"Sua {weapon_name} acerta o JEANO ({dmg} de dano, {max(jeano_hp,0)}/30 HP)."
        advance_turn(1.0)
        return

    for v in vex_units:
        if v["hp"] > 0 and (v["x"], v["y"]) == (tx, ty):
            dmg = random.randint(*WEAPON_DAMAGE)
            v["hp"] -= dmg
            if v["hp"] <= 0:
                lines = [f"Sua {weapon_name} destrói um VEX ({dmg} de dano)."]
                remaining = [u for u in vex_units if u["hp"] > 0]
                if not remaining and pirepli_quest_active:
                    pirepli_quest_active = False
                    artifact_infinite_energy = True
                    player_nation = "Itália (PIREPLI)"
                    lines.append("PIREPLI (via rádio): 'Impressionante. Bem-vindo à Itália, de verdade agora.' "
                                 "[ARTEFATO obtido: Núcleo Perpétuo] [NAÇÃO: Itália]")
                examine_msg = "  »  ".join(lines)
            else:
                rdmg = random.randint(2, 5)
                hp -= rdmg
                examine_msg = (f"Sua {weapon_name} acerta o VEX ({dmg} de dano, {v['hp']}/{VEX_MAX_HP} HP). "
                                f"VEX revida! Você perde {rdmg} HP ({max(hp,0)}/{max_hp}).")
            advance_turn(1.0)
            return

    examine_msg = "Não há nada pra atirar ali."

def aim_and_fire():
    global aim_cursor, examine_msg
    aim_cursor = (player_wx, player_wy)
    while True:
        reveal_around_player()
        draw_screen()
        safe_addstr(0, 0, " MIRA — setas movem, [1] confirma, [ESC] cancela ".center(100, '═'))
        stdscr.refresh()

        ch = stdscr.getch()
        cx, cy = aim_cursor
        if ch == 27:  # ESC
            aim_cursor = None
            examine_msg = "Mira cancelada."
            return
        elif ch == curses.KEY_UP and cy - 1 >= player_wy - WEAPON_RANGE:
            aim_cursor = (cx, cy - 1)
        elif ch == curses.KEY_DOWN and cy + 1 <= player_wy + WEAPON_RANGE:
            aim_cursor = (cx, cy + 1)
        elif ch == curses.KEY_LEFT and cx - 1 >= player_wx - WEAPON_RANGE:
            aim_cursor = (cx - 1, cy)
        elif ch == curses.KEY_RIGHT and cx + 1 <= player_wx + WEAPON_RANGE:
            aim_cursor = (cx + 1, cy)
        else:
            try:
                if chr(ch) == '1':
                    tx, ty = aim_cursor
                    aim_cursor = None
                    fire_at(tx, ty)
                    return
            except ValueError:
                pass

def _reset_run():
    """Reset completo — placeholder de game-over até definirmos a regra de verdade."""
    global player_wx, player_wy, turns, energy, hp, tether_active, mining_mode, examine_msg, heading_deg
    global inventory, has_leggero, turn_cost_per_move, turn_accum
    global artifact_infinite_energy, artifact_no_mining_damage
    global pirepli_hp, pirepli_hostile, pirepli_dead, pirepli_dmg_mult
    global jeano_hp, jeano_hostile, jeano_dead, jeano_dmg_mult
    global player_nation, has_vent_rapide, has_voltaire_lrhd, has_palatini, equipped_weapon
    global jeano_betrayed, pirepli_quest_active, vex_units
    global base_hp, cables, extractors, revealed_tiles, destroyed_rocks, destroyed_trees
    global PIREPLI_POS, JEANO_POS

    player_wx, player_wy = 0, 0
    turns = 0
    energy = 100.0
    hp = max_hp
    tether_active = True
    mining_mode = False
    examine_msg = "Nova run iniciada."
    heading_deg = 0

    inventory = {"minerio": 0, "madeira": 0, "diamante": 0, "pá": 0, "cicero_extractor": 0}
    has_leggero = False
    turn_cost_per_move = 1.0
    turn_accum = 0.0

    artifact_infinite_energy = False
    artifact_no_mining_damage = False

    pirepli_hp, pirepli_hostile, pirepli_dead, pirepli_dmg_mult = 30, False, False, 1.0
    jeano_hp, jeano_hostile, jeano_dead, jeano_dmg_mult = 30, False, False, 1.0
    PIREPLI_POS = (6, -3)
    JEANO_POS = (-8, 5)

    player_nation = None
    has_vent_rapide = False
    has_voltaire_lrhd = False
    has_palatini = False
    equipped_weapon = "voltaire"
    jeano_betrayed = False
    pirepli_quest_active = False
    vex_units = []

    base_hp = BASE_MAX_HP
    cables = set()
    extractors = {}
    revealed_tiles = set()
    destroyed_rocks = set()
    destroyed_trees = set()

def tick_extractors():
    for (wx, wy), ext in extractors.items():
        if ext["ticks"] < CICERO_DURATION:
            ext["ticks"] += 1
            target = round(CICERO_TOTAL * ext["ticks"] / CICERO_DURATION)
            gained = target - ext["given"]
            if gained > 0:
                ext["ready"] += gained
                ext["given"] += gained
            if ext["ticks"] >= CICERO_DURATION:
                destroyed_rocks.add((wx, wy))

def place_cicero():
    if inventory["cicero_extractor"] <= 0:
        return "Você não tem nenhum Cicero Extractor. Compre com o PIREPLI."
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            if dx == 0 and dy == 0:
                continue
            wx, wy = player_wx + dx, player_wy + dy
            if tile_type(wx, wy) == '#' and (wx, wy) not in extractors:
                extractors[(wx, wy)] = {"ticks": 0, "given": 0, "ready": 0}
                inventory["cicero_extractor"] -= 1
                return f"Cicero plantado. Vai render {CICERO_TOTAL} minérios em {CICERO_DURATION} turnos."
    return "Nenhuma rocha adjacente disponível."

def collect_cicero():
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            key = (player_wx + dx, player_wy + dy)
            if key in extractors and extractors[key]["ready"] > 0:
                got = extractors[key]["ready"]
                inventory["minerio"] += got
                extractors[key]["ready"] = 0
                return f"Coletou {got} minério(s) do Cicero."
    return "Nenhum Cicero com minério pronto por perto."

def advance_turn(cost):
    global turns, turn_accum
    turn_accum += cost
    whole = int(turn_accum)
    if whole > 0:
        turns += whole
        turn_accum -= whole
        for _ in range(whole):
            tick_extractors()
            pirepli_ai_turn()
            jeano_ai_turn()

def dig_ground():
    global energy
    if inventory["pá"] <= 0:
        return "Você precisa de uma Pá pra cavar. Fabrique uma na base [B]."
    if energy - DIG_ENERGY_COST < 0:
        return "EN insuficiente pra cavar."
    energy -= DIG_ENERGY_COST
    advance_turn(1.0)
    if random.random() < DIAMOND_CHANCE:
        inventory["diamante"] += 1
        return f"Você cavou e achou um DIAMANTE! (vale {DIAMANTE_VALOR_MINERIO} minérios)"
    return "Você cavou, mas só achou terra."

# ============================================
# LOOP PRINCIPAL
# ============================================
def main(scr):
    global stdscr, dist, player_wx, player_wy
    global turns, energy, hp, tether_active, mining_mode, heading_deg, examine_msg
    global has_leggero, turn_cost_per_move, artifact_infinite_energy, artifact_no_mining_damage
    global equipped_weapon, base_hp

    stdscr = scr
    curses.curs_set(0)
    stdscr.keypad(True)
    setup_colors()

    while True:
        dist = abs(player_wx) + abs(player_wy)

        if tether_active:
            connected_now = is_connected(player_wx, player_wy)
            if dist > max_tether_dist or not connected_now:
                # sem cabo até aqui: sem sustentação livre de energia
                pass
            else:
                loss_rate = 0.75 if has_leggero else 1.0
                target_limit = max(1, 100 - int((dist / max_tether_dist) * 99 * loss_rate))
                if energy < target_limit:
                    energy = min(target_limit, energy + 2)

        if energy <= 0:
            reveal_around_player()
            draw_screen()
            safe_addstr(VIEW_H + 10, 0, "[!] ENERGIA ZERADA. SISTEMA DESLIGANDO...".ljust(100))
            stdscr.refresh()
            time.sleep(2)

            target_turn = ((turns // DAY_LENGTH) + 1) * DAY_LENGTH
            turns = target_turn

            base_attacked = pirepli_hostile and not pirepli_dead
            if base_attacked:
                base_hp -= random.randint(20, 40)

            def storm_text():
                os.system('clear')
                print("""
                       ,
                      /
                     /
                  --/--
                   /
                  /
                 /
                """)
                print("KABOOOM! UMA TEMPESTADE DE RAIOS ATINGE O CHASSI DO XEON!")
                if base_attacked:
                    time.sleep(1)
                    print()
                    print(f"[!] Enquanto você estava AFK, o PIREPLI atacou a BASE. HP da base: {max(base_hp,0)}/{BASE_MAX_HP}")
                time.sleep(2.5)
            with_terminal(storm_text)

            if base_hp <= 0:
                def base_lost_text():
                    os.system('clear')
                    print("A BASE CAIU. Sem energia, sem fio, sem metrópole — o XEON desliga de vez.")
                    print()
                    print("[PLACEHOLDER] Sem regra de game-over definitiva ainda — reiniciando a run do zero.")
                    time.sleep(3)
                with_terminal(base_lost_text)
                _reset_run()
                continue

            energy = min(100, int(dist * 0.8) + 15)
            tether_active = False
            examine_msg = "Modo de emergência ativado. Volte para a base."
            continue

        if hp <= 0:
            reveal_around_player()
            draw_screen()
            safe_addstr(VIEW_H + 10, 0, "[!] XEON DESTRUÍDO EM COMBATE...".ljust(100))
            stdscr.refresh()
            time.sleep(2)

            def death_text():
                os.system('clear')
                print("O chassi do XEON cede sob o dano acumulado e desliga.")
                print()
                print("[PLACEHOLDER] Ainda não definimos regra de morte/respawn de verdade —")
                print("por enquanto, reativando no chassi reserva da base.")
                time.sleep(2.5)
            with_terminal(death_text)

            player_wx, player_wy = BASE_POS
            hp = max_hp
            energy = 60
            examine_msg = "Chassi reserva ativado na base. HP restaurado."
            continue

        reveal_around_player()
        draw_screen()

        ch = stdscr.getch()
        if ch == curses.KEY_UP:
            move = 'up'
        elif ch == curses.KEY_DOWN:
            move = 'down'
        elif ch == curses.KEY_LEFT:
            move = 'left'
        elif ch == curses.KEY_RIGHT:
            move = 'right'
        else:
            try:
                move = chr(ch).lower()
            except ValueError:
                move = ''

        if move != 'e':
            examine_msg = ""

        if move == 'q':
            break
        if move == 'c':
            tether_active = not tether_active
            continue
        if move == 'x':
            mining_mode = not mining_mode
            continue
        if move == 't':
            if is_adjacent_to_pirepli():
                with_terminal(_talk_to_pirepli_text)
            elif is_adjacent_to_jeano():
                with_terminal(_talk_to_jeano_text)
            else:
                examine_msg = "Ninguém por perto pra conversar."
            continue
        if move == 'v':
            examine_msg = place_cicero()
            continue
        if move == 'r':
            examine_msg = collect_cicero()
            continue
        if move == 'b':
            if is_on_base():
                with_terminal(_base_menu_text)
            else:
                examine_msg = "Precisa estar na base pra fabricar."
            continue
        if move == 'p':
            examine_msg = dig_ground()
            continue
        if move == 'i':
            with_terminal(_show_inventory_text)
            continue
        if move == 'y':
            artifact_infinite_energy = True
            examine_msg = "[DEBUG] Núcleo Perpétuo obtido."
            continue
        if move == 'u':
            artifact_no_mining_damage = True
            examine_msg = "[DEBUG] Blindagem Inabalável obtida."
            continue
        if move == '1':
            if has_voltaire_lrhd or has_palatini:
                aim_and_fire()
            else:
                examine_msg = "Nenhuma arma equipada."
            continue
        if move == 'n':
            if has_voltaire_lrhd and has_palatini:
                equipped_weapon = "palatini" if equipped_weapon == "voltaire" else "voltaire"
                nome = "Palatini Slip Cannon" if equipped_weapon == "palatini" else "Voltaire LRHD 04"
                examine_msg = f"Arma equipada: {nome}."
            else:
                examine_msg = "Você só tem uma arma — nada pra trocar ainda."
            continue

        if move == 'e':
            found_items = []
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    wx, wy = player_wx + dx, player_wy + dy
                    if (wx, wy) == BASE_POS:
                        found_items.append("BASE. Armazena minérios e fabrica tecnologias.")
                    elif (wx, wy) == PIREPLI_POS:
                        found_items.append("PIREPLI — andarilho italiano. Fale com [T].")
                    elif (wx, wy) == JEANO_POS:
                        found_items.append("JEANO — representante da França. Fale com [T] pra discutir aliança.")
                    elif (wx, wy) in extractors:
                        ext = extractors[(wx, wy)]
                        found_items.append(f"Cicero: {ext['ticks']}/{CICERO_DURATION} turnos, pronto: {ext['ready']}.")
                    elif tile_type(wx, wy) == '#':
                        found_items.append("Rocha densa. [X] pra minerar.")
                    elif tile_type(wx, wy) == 'T':
                        found_items.append("Árvore. [X] pra cortar.")
                    elif (wx, wy) in cables:
                        found_items.append("Fio de Energia. Conecta à base.")
            examine_msg = random.choice(found_items) if found_items else "Nada de interessante por perto."
            continue

        new_wx, new_wy = player_wx, player_wy
        moved = False
        if move == 'up':
            new_wy -= 1; moved = True; heading_deg = 0
        elif move == 'down':
            new_wy += 1; moved = True; heading_deg = 180
        elif move == 'left':
            new_wx -= 1; moved = True; heading_deg = 270
        elif move == 'right':
            new_wx += 1; moved = True; heading_deg = 90

        if moved:
            can_move = True
            mined_block = False
            old_connected = is_connected(player_wx, player_wy)
            target_tile = tile_type(new_wx, new_wy)

            if target_tile == '#':
                if mining_mode:
                    destroyed_rocks.add((new_wx, new_wy))
                    energy -= 5
                    if not artifact_no_mining_damage:
                        hp -= 1
                    inventory["minerio"] += random.randint(2, 4)
                    mined_block = True
                    can_move = False
                else:
                    can_move = False
            elif target_tile == 'T':
                if mining_mode:
                    destroyed_trees.add((new_wx, new_wy))
                    energy -= 3
                    inventory["madeira"] += random.randint(1, 3)
                    mined_block = True
                    can_move = False
                else:
                    can_move = False

            if can_move:
                new_dist = abs(new_wx) + abs(new_wy)
                lay_cable = tether_active and old_connected and new_dist <= CABLE_MAX_DIST

                player_wx, player_wy = new_wx, new_wy

                if lay_cable:
                    cables.add((player_wx, player_wy))

                # dreno de energia sempre que você NÃO tá conectado (base ou
                # em cima de um cabo já laçado) — independente de ter
                # desligado o tether manualmente ou só saído do alcance
                # físico do cabo (fix: antes ficava "congelado" nesse caso)
                if not artifact_infinite_energy and not mined_block and not is_connected(player_wx, player_wy):
                    if turns % 2 == 0:
                        energy -= 1 * wireless_efficiency

            advance_turn(1.0 if mined_block else turn_cost_per_move)
            mining_mode = False

if __name__ == "__main__":
    curses.wrapper(main)
    print("\nSistema encerrado.")

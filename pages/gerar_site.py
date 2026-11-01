#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera o site estatico do Pages em pages/saida/site (a imagem ja esta em fs/).

Reaproveita o curso e o front da VM. Troca os passos do Ghidra, que nao roda no
navegador, por outras ferramentas e ajusta as falas que so faziam sentido na VM.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
from html import escape

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
SITE = os.path.join(AQUI, "saida", "site")
WEB = os.path.join(RAIZ, "vm", "guia", "web")
NODE = os.path.join(AQUI, "node_modules")
BIOS = "https://raw.githubusercontent.com/copy/v86/cc37f35c43bf14865d74ad76879ecf9410f69eb1/bios/"

sys.path.insert(0, os.path.join(RAIZ, "vm", "guia"))
import curso  # noqa: E402

INTRO_FALAS = {
    "Essa VM é isolada: sem rede de verdade, com snapshot salvo. Se bagunçar, a gente volta o snapshot e finge que nada aconteceu. Como na vida.":
    "Essa VM roda dentro da aba do seu navegador, sem rede nenhuma. Se bagunçar, recarrega a página: o laboratório volta ao zero, seu progresso fica salvo, e a gente finge que nada aconteceu. Como na vida.",
}
# O Ghidra nao roda no navegador: cada passo dele volta com a ferramenta que
# responde a mesma pergunta aqui, conferida nas amostras de 32 bits.
SEM_GHIDRA = {
    ("caso001", "p6"): {
        "titulo": "A chave na unha",
        "tool": "terminal",
        "instr": "Hora de achar a chave na unha. A decrypt_strings faz XOR com o símbolo KEY. No Terminal, ache o endereço dele com objdump -t fatura_outubro | grep KEY e leia a seção com objdump -s -j .rodata fatura_outubro. O primeiro bloco da linha é o endereço. Qual o valor do byte que está nesse endereço?",
        "dica": "A linha sai assim: 804a000 2a000000 ... O primeiro bloco é o endereço, não é dado. O KEY é o primeiro par de dígitos do segundo bloco.",
        "sucesso": "0x2A. Achou a chave lendo o binário de verdade. Isso é engenharia reversa: o programa tentou esconder, você leu assim mesmo.",
    },
    ("caso003", "p4"): {"tool": "elf"},
    ("caso019", "p3"): {
        "tool": "strings",
        "instr": "Dentro do /proc/self/status tem um campo que vale 0 quando não há debugger e vira o PID do depurador quando tem um anexado. O nome dele precisa estar no binário pra ser comparado. Ache no Strings.",
        "dica": "Procure um texto terminado em dois-pontos, com 'Pid' no nome.",
    },
    ("caso020", "p5"): {
        "tool": "disasm",
        "instr": "Abra o Disassembler. Sem nomes, procure o laço de decodificação (um xor entre registradores). Logo antes dele, a chave é indexada: o compilador trocou 'i % N' por um 'and' com N-1. De quantos bytes é a chave?",
        "dica": "Procure 'and edx,0x3' perto do xor. And com 3 é o mesmo que resto da divisão por 4.",
    },
    ("caso025", "p3"): {
        "tool": "disasm",
        "instr": "No Disassembler, ache a chamada a process_vm_writev: o primeiro argumento é o PID alvo. Nesta amostra didática, de onde vem esse PID (qual função é chamada logo antes)?",
    },
}
TROCAS = [("Abra o Disassembler (ou Ghidra).", "Abra o Disassembler."),
          ("O algoritmo (visível no Ghidra) é", "O algoritmo (visível no Disassembler) é"),
          ("você renomeia funções no Ghidra até", "você renomeia funções no decompilador até"),
          ("antes de abrir o Ghidra, a tabela", "antes de abrir o desmontador, a tabela"),
          ("antes mesmo de abrir no Ghidra", "antes mesmo de desmontar"),
          # A musl de 32 bits chama open, nao openat.
          ("open/openat", "open"), ("openat", "open")]
LINK_LICENCAS = '<a href="licencas.html" target="_blank" rel="noopener" style="%s">licenças</a>'
HTML_TROCAS = [("rede: FakeNet", "rede: desligada"), ("snapshot: salvo", "progresso: salvo"),
               ('"  (abre o programa)"', '""'), ('" (abre o programa de verdade)"', '" (abre a ferramenta)"'),
               ('<button class="btn-ghost" id="btnVoltar">',
                LINK_LICENCAS % "color:inherit;font-size:12px;opacity:.75;align-self:center"
                + '\n      <button class="btn-ghost" id="btnVoltar">'),
               ('<div class="toque">mova o mouse para olhar a sala</div>',
                '<div class="toque">mova o mouse para olhar a sala</div>\n  '
                + LINK_LICENCAS % "position:absolute;bottom:14px;left:18px;z-index:5;pointer-events:auto;color:#fff;font-size:12px;opacity:.75"),
               ("Não consegui falar com o servidor local. Rode: python3 servidor.py",
                "Não consegui falar com o Linux do laboratório. Recarregue a página."),
               ("Não consegui falar com o servidor local. Ele está rodando? (python3 servidor.py)",
                "Não consegui falar com o Linux do laboratório. Recarregue a página.")]
# Ferramenta que o passo ajustado passa a pedir e que o caso nao listava.
TOOLS_EXTRAS = {"caso025": ["disasm"]}
# A barra lateral so cita o que esta nesta imagem.
TOOLS_NO_SITE = {"hex": {"real": "xxd"}, "strings": {"real": "strings"}, "disasm": {"real": "objdump"},
                 "entropia": {"real": "python"}, "cat": {"real": "cat"},
                 "tshark": {"real": "tshark, o Wireshark de terminal"}}


def hashes():
    r = {}
    with open(os.path.join(SITE, "fs", "sha256.txt")) as f:
        for linha in f:
            h, nome = linha.split()
            r[nome.lstrip("./")] = h
    return r


def montar_curso():
    sha = hashes()
    casos = []
    for c in curso.CASOS:
        passos = []
        for p in c["passos"]:
            p = dict(p, **SEM_GHIDRA.get((c["id"], p["id"]), {}))
            assert p["tool"] != "ghidra", (c["id"], p["id"])
            for campo in ("instr", "dica", "sucesso"):
                for de, para in TROCAS:
                    p[campo] = p[campo].replace(de, para)
            passos.append(p)
        tools = [dict(curso.TOOLS[t], id=t, **TOOLS_NO_SITE.get(t, {}))
                 for t in c["tools"] + TOOLS_EXTRAS.get(c["id"], []) if t != "ghidra"]
        casos.append({"id": c["id"], "nome": c["nome"], "nivel": c["nivel"],
                      "arquivo": c["arquivo"], "origem": c["origem"],
                      "sha256": sha[c["dir"] + "/" + c["arquivo"]],
                      "tools": tools, "passos": passos})
    intro = dict(curso.INTRO)
    intro["falas"] = [INTRO_FALAS.get(f, f) for f in intro["falas"]]
    # Nenhum texto do jogo pode mandar o aluno pra uma ferramenta que nao existe aqui.
    assert "ghidra" not in json.dumps(casos, ensure_ascii=False).lower()
    return {"intro": intro, "casos": casos}


def copiar(origem, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copyfile(origem, destino)


# Copia do codigo-fonte, enviada por imagem/fontes.sh com a mesma regra de licenca.
FONTES = "https://github.com/marianabsctba/Panthera_Quarentena/releases/download/fontes/"
SEABIOS = "1.16.2"


def projetos_do_linux():
    """Agrupa os pacotes da imagem por projeto de origem."""
    grupos = {}
    with open(os.path.join(AQUI, "saida", "pacotes.tsv"), encoding="utf-8") as f:
        for linha in f:
            pacote, versao, origem, licenca, commit, repo, site = linha.rstrip("\n").split("\t")
            # O endereco declarado no pacote do Alpine saiu do ar.
            site = site.replace("https://facebook.github.io/zstd/", "https://github.com/facebook/zstd")
            g = grupos.setdefault(origem, {"origem": origem, "versao": versao, "licencas": [], "pacotes": [],
                                           "commit": commit, "repo": repo, "site": site})
            g["pacotes"].append(pacote)
            if re.search("GPL|MPL", licenca):
                g["copia"] = f"{FONTES}{origem}-{versao}.tar.gz"
            if licenca not in g["licencas"]:
                g["licencas"].append(licenca)
    # Sem estes a lista esta errada: melhor falhar o build que publicar sem o aviso.
    for obrigatorio in ("linux-lts", "busybox", "bash", "binutils", "wireshark", "upx"):
        assert obrigatorio in grupos, "falta na lista de licencas: " + obrigatorio
    return [grupos[o] for o in sorted(grupos)]


def gerar_licencas():
    destino = os.path.join(SITE, "licencas")
    os.makedirs(destino, exist_ok=True)
    origem = os.path.join(AQUI, "web", "licencas")
    textos = sorted(os.listdir(origem))
    for nome in textos:
        copiar(os.path.join(origem, nome), os.path.join(destino, nome))
    for pacote, nome in [("v86", "v86.txt"), ("@xterm/xterm", "xterm.txt"), ("@xterm/addon-fit", "addon-fit.txt")]:
        copiar(os.path.join(NODE, *pacote.split("/"), "LICENSE"), os.path.join(destino, nome))

    def versao_npm(pacote):
        with open(os.path.join(NODE, *pacote.split("/"), "package.json"), encoding="utf-8") as f:
            return json.load(f)["version"].split("+")[0]

    # A versao fica numa variavel minificada: REVISION=e, com const e="128" no comeco.
    with open(os.path.join(WEB, "vendor", "three.min.js"), encoding="utf-8") as f:
        three = re.search(r'"use strict";const \w+="(\d+)"', f.read()).group(1)
    v86_url = "https://github.com/copy/v86/tree/" + BIOS.split("/")[-3]
    navegador = [
        ("v86", versao_npm("v86"), "BSD-2-Clause", "licencas/v86.txt", v86_url),
        ("xterm.js", versao_npm("@xterm/xterm"), "MIT", "licencas/xterm.txt", "https://github.com/xtermjs/xterm.js"),
        ("addon-fit do xterm.js", versao_npm("@xterm/addon-fit"), "MIT", "licencas/addon-fit.txt", "https://github.com/xtermjs/xterm.js"),
        ("three.js", "r" + three, "MIT", "vendor/three.min.js", "https://github.com/mrdoob/three.js/tree/r" + three),
        ("SeaBIOS (seabios.bin e vgabios.bin)", SEABIOS, "LGPL-3.0", "licencas/LGPL-3.0-only.txt",
         f"{FONTES}seabios-{SEABIOS}.tar.gz"),
    ]
    linhas_nav = "".join(
        f'<tr><td>{escape(n)}</td><td>{escape(v)}</td><td><a href="{t}">{escape(l)}</a></td>'
        f'<td><a href="{u}">código-fonte</a></td></tr>\n' for n, v, l, t, u in navegador)

    projetos = projetos_do_linux()
    linhas_linux = "".join(
        f'<tr><td>{escape(p["origem"])}<small>{escape(", ".join(p["pacotes"]))}</small></td>'
        f'<td>{escape(p["versao"])}</td><td>{escape("; ".join(p["licencas"]))}</td>'
        '<td>' + (f'<a href="{escape(p["copia"])}">código-fonte</a> · ' if "copia" in p else "")
        + f'<a href="https://gitlab.alpinelinux.org/alpine/aports/-/tree/{p["commit"]}/{p["repo"]}/{escape(p["origem"])}">receita</a>'
        + (f' · <a href="{escape(p["site"])}">projeto</a>' if p["site"] else "") + "</td></tr>\n"
        for p in projetos)
    lista_textos = "".join(f'<li><a href="licencas/{n}">{escape(n[:-4])}</a></li>' for n in textos)

    pagina = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Licenças | Panthera Quarentena</title>
<style>
:root {{ --fundo:#0a0a0d; --texto:#ece9ee; --suave:#a59fa9; --rosa:#ff3d9a; --linha:#2b2830; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--fundo); color:var(--texto); font:16px/1.6 system-ui,sans-serif; }}
main {{ max-width:960px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ color:var(--rosa); margin:0 0 12px; font-size:30px; }}
h2 {{ margin:36px 0 8px; font-size:20px; }}
a {{ color:var(--rosa); }}
.tabela {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th,td {{ text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--linha); }}
th {{ color:var(--suave); font-weight:600; }}
td:nth-child(2),td:last-child {{ white-space:nowrap; }}
small {{ display:block; color:var(--suave); font-size:12px; }}
ul {{ padding-left:20px; }}
</style>
</head>
<body>
<main>
<h1>Licenças</h1>
<p>O Panthera Quarentena liga um Linux de verdade dentro da sua aba. Para isso, o navegador baixa programas de vários projetos de software livre, cada um com a sua licença. Esta página lista todos eles, com a versão e o caminho para o código-fonte.</p>

<h2>O jogo</h2>
<p>O código do jogo, os casos e as amostras estão sob a <a href="https://github.com/marianabsctba/Panthera_Quarentena/blob/main/LICENSE">licença MIT</a>, no <a href="https://github.com/marianabsctba/Panthera_Quarentena">repositório do projeto</a>. Os programas listados abaixo são obras independentes e continuam sob as licenças deles.</p>

<h2>O que roda na página</h2>
<div class="tabela"><table>
<thead><tr><th>Projeto</th><th>Versão</th><th>Licença</th><th>Fonte</th></tr></thead>
<tbody>
{linhas_nav}</tbody>
</table></div>

<h2>O que roda no Linux</h2>
<p>São os pacotes oficiais do Alpine Linux 3.21 para x86, sem alteração nos programas. Para caber no navegador, a imagem leva menos módulos do kernel e nenhuma documentação. O <a href="https://github.com/marianabsctba/Panthera_Quarentena/blob/main/pages/imagem/construir.sh">script de montagem</a> mostra cada passo.</p>
<p>Os programas sob GPL, LGPL ou MPL têm uma cópia do código-fonte guardada neste projeto, na <a href="https://github.com/marianabsctba/Panthera_Quarentena/releases/tag/fontes">página de arquivos</a>: cada arquivo traz a receita de compilação, com os patches, e os arquivos originais daquela versão. Os demais têm a receita, que aponta para o código original, também disponível no <a href="https://distfiles.alpinelinux.org/distfiles/v3.21/">acervo do Alpine</a>.</p>
<div class="tabela"><table>
<thead><tr><th>Projeto e pacotes</th><th>Versão</th><th>Licença declarada</th><th>Fonte</th></tr></thead>
<tbody>
{linhas_linux}</tbody>
</table></div>
<p><small>As licenças acima são as declaradas nos pacotes do Alpine. Se houver diferença, vale o arquivo de licença do próprio projeto, que acompanha o código-fonte.</small></p>

<h2>Textos das licenças</h2>
<ul>{lista_textos}</ul>
<p>As demais licenças curtas, como MIT e BSD, têm o texto e os avisos de autoria dentro do código-fonte de cada projeto.</p>

<h2>Sem garantia</h2>
<p>Estes programas são distribuídos sem nenhuma garantia, nos termos das licenças de cada um.</p>
</main>
</body>
</html>
"""
    with open(os.path.join(SITE, "licencas.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(pagina)


def main():
    with open(os.path.join(SITE, "curso.json"), "w", encoding="utf-8") as f:
        json.dump(montar_curso(), f, ensure_ascii=False)
    gerar_licencas()

    vendor = os.path.join(SITE, "vendor")
    copiar(os.path.join(WEB, "panthera.webp"), os.path.join(SITE, "panthera.webp"))
    copiar(os.path.join(WEB, "vendor", "three.min.js"), os.path.join(vendor, "three.min.js"))
    for origem, nome in [("v86/build/libv86.js", "libv86.js"), ("v86/build/v86.wasm", "v86.wasm"),
                         ("@xterm/xterm/lib/xterm.js", "xterm.js"), ("@xterm/xterm/css/xterm.css", "xterm.css"),
                         ("@xterm/addon-fit/lib/addon-fit.js", "addon-fit.js")]:
        copiar(os.path.join(NODE, *origem.split("/")), os.path.join(vendor, nome))
    for b in ("seabios.bin", "vgabios.bin"):
        destino = os.path.join(vendor, b)
        if not os.path.exists(destino):
            urllib.request.urlretrieve(BIOS + b, destino)

    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
        html = f.read()
    extras = ('<link rel="stylesheet" href="vendor/xterm.css">\n'
              '<script src="vendor/libv86.js"></script>\n'
              '<script src="vendor/xterm.js"></script>\n'
              '<script src="vendor/addon-fit.js"></script>\n'
              '<script src="navegador.js"></script>\n')
    marca = '<script src="vendor/three.min.js"></script>\n'
    if marca not in html:
        html = html.replace(marca.strip(), marca.strip() + "\n")
    for de, para in HTML_TROCAS:
        html = html.replace(de, para)
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(html.replace(marca, marca + extras, 1))

    # O estado guarda a arvore de arquivos: estado e imagem de versoes diferentes
    # travam o Linux. A versao no nome impede que o cache misture os dois.
    with open(os.path.join(SITE, "fs", "fs.json"), "rb") as f:
        versao = hashlib.sha256(f.read()).hexdigest()[:12]
    for nome in ("sw.js", "navegador.js"):
        with open(os.path.join(AQUI, "web", nome), encoding="utf-8") as f:
            texto = f.read().replace("__VERSAO__", versao)
        with open(os.path.join(SITE, nome), "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
    with open(os.path.join(AQUI, "saida", "versao.txt"), "w") as f:
        f.write(versao)
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print("ok:", SITE)


if __name__ == "__main__":
    main()
